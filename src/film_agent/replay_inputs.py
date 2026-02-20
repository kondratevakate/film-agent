"""Replay authoritative JSON inputs through the run state-machine flow."""

from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from film_agent.config import load_config
from film_agent.io.json_io import dump_canonical_json, load_json
from film_agent.state_machine.orchestrator import run_gate0, submit_agent, validate_gate
from film_agent.state_machine.state_store import iteration_key, load_state, run_dir

REPLAY_SEQUENCE: tuple[tuple[str, str, int | None], ...] = (
    ("showrunner", "COLLECT_SHOWRUNNER", 1),
    ("direction", "COLLECT_DIRECTION", 2),
    ("dance_mapping", "COLLECT_DANCE_MAPPING", 3),
    ("cinematography", "COLLECT_CINEMATOGRAPHY", None),
    ("audio", "COLLECT_AUDIO", None),
    ("final_metrics", "FINAL_RENDER", 4),
)

AGENT_FILENAME_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    "showrunner": (
        re.compile(r"(^|[._-])showrunner([._-]|$)", re.IGNORECASE),
        re.compile(r"(^|[._-])script([._-]|$)", re.IGNORECASE),
    ),
    "direction": (re.compile(r"(^|[._-])direction([._-]|$)", re.IGNORECASE),),
    "dance_mapping": (re.compile(r"(^|[._-])dance[_-]?mapping([._-]|$)", re.IGNORECASE),),
    "cinematography": (
        re.compile(r"(^|[._-])cinematography([._-]|$)", re.IGNORECASE),
        re.compile(r"(^|[._-])selected[_-]?images([._-]|$)", re.IGNORECASE),
    ),
    "audio": (
        re.compile(r"(^|[._-])audio([._-]|$)", re.IGNORECASE),
        re.compile(r"(^|[._-])av[_-]?prompt", re.IGNORECASE),
    ),
    "final_metrics": (re.compile(r"(^|[._-])final[_-]?metrics([._-]|$)", re.IGNORECASE),),
}


def replay_inputs_for_run(
    base_dir: Path,
    run_id: str,
    *,
    inputs_dir: Path | None = None,
    prefer_current: bool = True,
    warn_only_missing: bool = True,
    stop_on_missing: bool = True,
) -> dict[str, Any]:
    """Submit authoritative JSON inputs to the run in strict gate order."""

    run_path = run_dir(base_dir, run_id)
    state = load_state(run_path)
    config_path = Path(state.config_path)
    config = load_config(config_path)

    primary_dir, legacy_dir = _resolve_input_roots(
        state_project_name=state.project_name,
        config_path=config_path,
        inputs_dir=inputs_dir,
    )

    warnings: list[str] = []
    actions: list[dict[str, Any]] = []
    stopped_reason: str | None = None

    replay_dir = run_path / "replay_inputs"
    replay_dir.mkdir(parents=True, exist_ok=True)

    state = load_state(run_path)
    if state.current_state == "GATE0":
        gate0_result = run_gate0(base_dir, run_id)
        actions.append({"kind": "validate", "gate": 0, "state": gate0_result.state, "detail": gate0_result.detail})
        if gate0_result.state == "FAILED":
            stopped_reason = "gate0_failed"
            return {
                "run_id": run_id,
                "project_name": config.project_name,
                "inputs_primary_dir": str(primary_dir) if primary_dir else None,
                "inputs_legacy_dir": str(legacy_dir) if legacy_dir else None,
                "prefer_current": prefer_current,
                "warn_only_missing": warn_only_missing,
                "stop_on_missing": stop_on_missing,
                "actions": actions,
                "warnings": warnings,
                "stopped_reason": stopped_reason,
                "current_state": load_state(run_path).current_state,
                "current_iteration": load_state(run_path).current_iteration,
            }

    for agent, expected_state, gate in REPLAY_SEQUENCE:
        state = load_state(run_path)
        if state.current_state in {"FAILED", "COMPLETE"}:
            stopped_reason = f"state_{state.current_state.lower()}"
            break

        if state.current_state != expected_state:
            stopped_reason = (
                f"state_mismatch_for_{agent}: expected {expected_state}, got {state.current_state}"
            )
            warnings.append(stopped_reason)
            break

        source_file, source_root = _pick_agent_input_file(
            agent=agent,
            primary_dir=primary_dir,
            legacy_dir=legacy_dir,
            prefer_current=prefer_current,
        )
        if source_file is None:
            message = f"Missing input JSON for agent '{agent}'."
            if warn_only_missing:
                warnings.append(message)
                if stop_on_missing:
                    stopped_reason = f"missing_{agent}"
                    break
                continue
            raise ValueError(message)

        payload_raw = load_json(source_file)
        if not isinstance(payload_raw, dict):
            raise ValueError(f"Input JSON for agent '{agent}' must be an object: {source_file}")
        payload = patch_payload_links(agent=agent, payload=payload_raw, state=state)

        staged_path = replay_dir / f"{agent}.{iteration_key(state.current_iteration)}.replay.json"
        dump_canonical_json(staged_path, payload)

        submit_result = submit_agent(base_dir, run_id, agent, staged_path)
        actions.append(
            {
                "kind": "submit",
                "agent": agent,
                "input_file": str(source_file),
                "input_root": str(source_root) if source_root else None,
                "staged_file": str(staged_path),
                "state": submit_result.state,
                "detail": submit_result.detail,
            }
        )

        if gate is not None:
            gate_result = validate_gate(base_dir, run_id, gate)
            actions.append({"kind": "validate", "gate": gate, "state": gate_result.state, "detail": gate_result.detail})
            report_path = Path(gate_result.detail["report"])
            report_payload = load_json(report_path)
            passed = bool(report_payload.get("passed", False))
            if not passed:
                stopped_reason = f"gate{gate}_failed"
                break

    latest_state = load_state(run_path)
    return {
        "run_id": run_id,
        "project_name": config.project_name,
        "inputs_primary_dir": str(primary_dir) if primary_dir else None,
        "inputs_legacy_dir": str(legacy_dir) if legacy_dir else None,
        "prefer_current": prefer_current,
        "warn_only_missing": warn_only_missing,
        "stop_on_missing": stop_on_missing,
        "actions": actions,
        "warnings": warnings,
        "stopped_reason": stopped_reason,
        "current_state": latest_state.current_state,
        "current_iteration": latest_state.current_iteration,
    }


def patch_payload_links(*, agent: str, payload: dict[str, Any], state) -> dict[str, Any]:
    """Patch state-linked identifiers before submission."""

    out = dict(payload)

    if agent == "dance_mapping":
        if not state.latest_direction_pack_id:
            raise ValueError("Cannot patch dance_mapping.script_review_id without latest_direction_pack_id.")
        out["script_review_id"] = state.latest_direction_pack_id
        return out

    if agent == "cinematography":
        if not state.latest_image_prompt_package_id:
            raise ValueError("Cannot patch cinematography.image_prompt_package_id without latest_image_prompt_package_id.")
        out["image_prompt_package_id"] = state.latest_image_prompt_package_id
        return out

    if agent == "audio":
        if not state.latest_image_prompt_package_id:
            raise ValueError("Cannot patch audio.image_prompt_package_id without latest_image_prompt_package_id.")
        if not state.latest_selected_images_id:
            raise ValueError("Cannot patch audio.selected_images_id without latest_selected_images_id.")
        out["image_prompt_package_id"] = state.latest_image_prompt_package_id
        out["selected_images_id"] = state.latest_selected_images_id
        return out

    if agent == "final_metrics":
        if not state.locked_spec_hash:
            raise ValueError("Cannot patch final_metrics.spec_hash without locked_spec_hash.")
        out["spec_hash"] = state.locked_spec_hash
        out.setdefault("one_shot_render", True)
        return out

    return out


def select_input_file(candidates: list[Path], *, prefer_current: bool) -> Path:
    """Select one candidate deterministically, preferring `*.current.json` by default."""

    if not candidates:
        raise ValueError("No candidates provided for input selection.")

    def _is_current(path: Path) -> bool:
        name = path.name.casefold()
        return ".current." in name or name.endswith(".current.json")

    def _rank(path: Path) -> tuple[int, int, str]:
        current = _is_current(path)
        priority = 0 if (current if prefer_current else not current) else 1
        return (priority, len(path.name), path.name.casefold())

    return min(candidates, key=_rank)


def _resolve_input_roots(*, state_project_name: str, config_path: Path, inputs_dir: Path | None) -> tuple[Path | None, Path | None]:
    if inputs_dir is not None:
        resolved = inputs_dir.expanduser().resolve()
        if not resolved.exists():
            raise ValueError(f"inputs_dir does not exist: {resolved}")
        if not resolved.is_dir():
            raise ValueError(f"inputs_dir must be a directory: {resolved}")
        return resolved, None

    config_dir = config_path.resolve().parent
    project_dir = config_dir / state_project_name
    primary = project_dir / "inputs"
    legacy = project_dir
    return primary, legacy


def _pick_agent_input_file(
    *,
    agent: str,
    primary_dir: Path | None,
    legacy_dir: Path | None,
    prefer_current: bool,
) -> tuple[Path | None, Path | None]:
    primary_matches = _find_agent_matches(primary_dir, agent) if primary_dir is not None else []
    if primary_matches:
        return select_input_file(primary_matches, prefer_current=prefer_current), primary_dir

    legacy_matches = _find_agent_matches(legacy_dir, agent) if legacy_dir is not None else []
    if legacy_matches:
        return select_input_file(legacy_matches, prefer_current=prefer_current), legacy_dir
    return None, None


def _find_agent_matches(folder: Path | None, agent: str) -> list[Path]:
    if folder is None or not folder.exists() or not folder.is_dir():
        return []
    patterns = AGENT_FILENAME_PATTERNS[agent]
    matches: list[Path] = []
    for path in sorted(folder.glob("*.json")):
        name = path.name
        if any(pattern.search(name) for pattern in patterns):
            matches.append(path)
    return matches
