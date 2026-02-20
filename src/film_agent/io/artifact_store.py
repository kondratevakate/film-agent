"""Artifact ingestion and retrieval."""

from __future__ import annotations

import json
from pathlib import Path

from pydantic import ValidationError

from film_agent.constants import REQUIRED_PREPROD_ARTIFACTS, RunState
from film_agent.io.hashing import sha256_file, sha256_json
from film_agent.io.json_io import dump_canonical_json, load_json
from film_agent.schemas.registry import AGENT_ARTIFACTS
from film_agent.state_machine.state_store import (
    IterationArtifactRecord,
    RunStateData,
    append_event,
    get_iteration_record,
    iteration_key,
    utc_now_iso,
)


class ArtifactError(ValueError):
    """Validation error raised during artifact submission."""


def artifact_path_for_agent(run_path: Path, iteration: int, agent: str) -> Path:
    entry = AGENT_ARTIFACTS[agent]
    return run_path / "iterations" / iteration_key(iteration) / "artifacts" / entry.filename


def load_artifact_for_agent(run_path: Path, state: RunStateData, agent: str):
    record = state.iterations.get(iteration_key(state.current_iteration))
    if not record or agent not in record.artifacts:
        return None
    path = Path(record.artifacts[agent].path)
    model = AGENT_ARTIFACTS[agent].model
    return model.model_validate(load_json(path))


def require_artifacts(state: RunStateData) -> list[str]:
    record = state.iterations.get(iteration_key(state.current_iteration))
    missing: list[str] = []
    if not record:
        return list(REQUIRED_PREPROD_ARTIFACTS)
    for agent in REQUIRED_PREPROD_ARTIFACTS:
        if agent not in record.artifacts:
            missing.append(agent)
    return missing


def submit_artifact(run_path: Path, state: RunStateData, agent: str, input_file: Path) -> dict[str, str]:
    if agent not in AGENT_ARTIFACTS:
        raise ArtifactError(f"Unsupported agent '{agent}'.")

    entry = AGENT_ARTIFACTS[agent]
    try:
        payload = json.loads(input_file.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ArtifactError(f"Input file is not valid JSON: {exc}") from exc

    try:
        artifact = entry.model.model_validate(payload)
    except ValidationError as exc:
        raise ArtifactError(f"Schema validation failed: {exc}") from exc

    if agent == "dance_mapping":
        if not state.latest_direction_pack_id:
            raise ArtifactError("Script review artifact is required before image prompt package.")
        if artifact.script_review_id != state.latest_direction_pack_id:
            raise ArtifactError(
                "ImagePromptPackage.script_review_id must match current ScriptReview id "
                f"({state.latest_direction_pack_id})."
            )
    if agent == "cinematography":
        if not state.latest_image_prompt_package_id:
            raise ArtifactError("Image prompt package is required before selected images.")
        if artifact.image_prompt_package_id != state.latest_image_prompt_package_id:
            raise ArtifactError(
                "SelectedImagesArtifact.image_prompt_package_id must match current image prompt package id "
                f"({state.latest_image_prompt_package_id})."
            )
    if agent == "audio":
        if not state.latest_image_prompt_package_id or not state.latest_selected_images_id:
            raise ArtifactError("Image prompt package and selected images are required before AV prompts.")
        if artifact.image_prompt_package_id != state.latest_image_prompt_package_id:
            raise ArtifactError(
                "AVPromptPackage.image_prompt_package_id must match current image prompt package id "
                f"({state.latest_image_prompt_package_id})."
            )
        if artifact.selected_images_id != state.latest_selected_images_id:
            raise ArtifactError(
                "AVPromptPackage.selected_images_id must match current selected images id "
                f"({state.latest_selected_images_id})."
            )

    target = artifact_path_for_agent(run_path, state.current_iteration, agent)
    dump_canonical_json(target, artifact.model_dump(mode="json"))

    record = get_iteration_record(state)
    checksum = sha256_file(target)
    record.artifacts[agent] = IterationArtifactRecord(
        path=str(target),
        sha256=checksum,
        submitted_at=utc_now_iso(),
    )

    if agent == "direction":
        state.latest_direction_pack_id = sha256_json(artifact.model_dump(mode="json"))
    if agent == "dance_mapping":
        state.latest_image_prompt_package_id = sha256_json(artifact.model_dump(mode="json"))
    if agent == "cinematography":
        state.latest_selected_images_id = sha256_json(artifact.model_dump(mode="json"))

    append_event(
        run_path,
        "artifact_submitted",
        {
            "iteration": state.current_iteration,
            "agent": agent,
            "path": str(target),
            "sha256": checksum,
        },
    )
    transition_state_after_submit(state, agent)

    return {"path": str(target), "sha256": checksum}


def transition_state_after_submit(state: RunStateData, agent: str) -> None:
    transitions: dict[tuple[str, str], str] = {
        (RunState.COLLECT_SHOWRUNNER, "showrunner"): RunState.GATE1,
        (RunState.COLLECT_DIRECTION, "direction"): RunState.GATE2,
        (RunState.COLLECT_DANCE_MAPPING, "dance_mapping"): RunState.GATE3,
        (RunState.COLLECT_CINEMATOGRAPHY, "cinematography"): RunState.COLLECT_AUDIO,
        (RunState.COLLECT_AUDIO, "audio"): RunState.LOCK_PREPROD,
    }
    next_state = transitions.get((state.current_state, agent))
    if next_state:
        state.current_state = next_state
