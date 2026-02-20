"""State persistence for file-based orchestration."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any
from uuid import uuid4

from pydantic import BaseModel, Field

from film_agent.config import RunConfig, config_dict_for_hash
from film_agent.constants import GATE_NAMES, RunState
from film_agent.io.hashing import sha256_json
from film_agent.io.json_io import dump_canonical_json, load_json


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def iteration_key(iteration: int) -> str:
    return f"iter-{iteration:02d}"


class IterationArtifactRecord(BaseModel):
    path: str
    sha256: str
    submitted_at: str


class IterationRecord(BaseModel):
    artifacts: dict[str, IterationArtifactRecord] = Field(default_factory=dict)


class RunStateData(BaseModel):
    run_id: str
    project_name: str
    created_at: str
    updated_at: str
    config_path: str
    config_hash: str
    science_source_pdf: str | None = None
    science_source_hash: str | None = None
    current_state: str = RunState.GATE0
    current_iteration: int = 1
    gate_status: dict[str, str] = Field(default_factory=dict)
    retry_counts: dict[str, int] = Field(default_factory=dict)
    provider_policy: dict[str, str] = Field(default_factory=dict)
    active_video_provider: str | None = None
    latest_direction_pack_id: str | None = None
    latest_image_prompt_package_id: str | None = None
    latest_selected_images_id: str | None = None
    preprod_locked_iteration: int | None = None
    locked_spec_hash: str | None = None
    iterations: dict[str, IterationRecord] = Field(default_factory=dict)


def default_gate_status() -> dict[str, str]:
    return {gate: "pending" for gate in GATE_NAMES}


def default_retry_counts() -> dict[str, int]:
    return {"gate1": 0, "gate2": 0, "gate3": 0}


def build_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    return f"run-{stamp}-{str(uuid4())[:8]}"


def run_dir(base_dir: Path, run_id: str) -> Path:
    return base_dir / "runs" / run_id


def ensure_run_layout(path: Path) -> None:
    (path / "iterations" / "iter-01" / "artifacts").mkdir(parents=True, exist_ok=True)
    (path / "gate_reports").mkdir(parents=True, exist_ok=True)
    (path / "locks").mkdir(parents=True, exist_ok=True)
    (path / "exports").mkdir(parents=True, exist_ok=True)
    (path / "events.jsonl").touch(exist_ok=True)


def new_state(config_path: Path, config: RunConfig) -> RunStateData:
    return RunStateData(
        run_id=build_run_id(),
        project_name=config.project_name,
        created_at=utc_now_iso(),
        updated_at=utc_now_iso(),
        config_path=str(config_path),
        config_hash=sha256_json(config_dict_for_hash(config)),
        science_source_pdf=config.science_source_pdf,
        current_state=RunState.GATE0,
        gate_status=default_gate_status(),
        retry_counts=default_retry_counts(),
        provider_policy={
            "audio": config.providers.audio,
            "image_primary": config.providers.image_primary,
            "image_secondary": config.providers.image_secondary,
            "video_primary": config.providers.video_primary,
            "video_fallback": config.providers.video_fallback,
        },
        active_video_provider=config.providers.video_primary,
        iterations={iteration_key(1): IterationRecord()},
    )


def state_path(path: Path) -> Path:
    return path / "state.json"


def load_state(path: Path) -> RunStateData:
    payload = load_json(state_path(path))
    return RunStateData.model_validate(payload)


def save_state(path: Path, state: RunStateData) -> None:
    state.updated_at = utc_now_iso()
    dump_canonical_json(state_path(path), state.model_dump(mode="json"))


def append_event(path: Path, event_type: str, payload: dict[str, Any]) -> None:
    line = {
        "at": utc_now_iso(),
        "event": event_type,
        "payload": payload,
    }
    events_path = path / "events.jsonl"
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(line, ensure_ascii=True, sort_keys=True) + "\n")


def get_iteration_record(state: RunStateData) -> IterationRecord:
    key = iteration_key(state.current_iteration)
    if key not in state.iterations:
        state.iterations[key] = IterationRecord()
    return state.iterations[key]


def start_next_iteration(path: Path, state: RunStateData, reason: str, carry_forward: bool = True) -> None:
    prev_iter = state.current_iteration
    state.current_iteration += 1
    new_key = iteration_key(state.current_iteration)
    prev_key = iteration_key(prev_iter)

    new_artifact_dir = path / "iterations" / new_key / "artifacts"
    new_artifact_dir.mkdir(parents=True, exist_ok=True)
    state.iterations[new_key] = IterationRecord()

    if carry_forward and prev_key in state.iterations:
        prev_record = state.iterations[prev_key]
        for agent, item in prev_record.artifacts.items():
            src = Path(item.path)
            dst = new_artifact_dir / src.name
            dst.write_bytes(src.read_bytes())
            state.iterations[new_key].artifacts[agent] = IterationArtifactRecord(
                path=str(dst),
                sha256=item.sha256,
                submitted_at=utc_now_iso(),
            )

    append_event(
        path,
        "iteration_started",
        {
            "from_iteration": prev_iter,
            "to_iteration": state.current_iteration,
            "reason": reason,
            "carry_forward": carry_forward,
        },
    )
