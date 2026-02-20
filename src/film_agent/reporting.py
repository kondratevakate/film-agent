"""Reporting helpers."""

from __future__ import annotations

from pathlib import Path

from film_agent.io.json_io import dump_canonical_json, load_json
from film_agent.state_machine.state_store import iteration_key, load_state, run_dir


def build_final_report(base_dir: Path, run_id: str) -> Path:
    path = run_dir(base_dir, run_id)
    state = load_state(path)

    gate_reports: dict[str, dict] = {}
    for gate in ("gate0", "gate1", "gate2", "gate3", "gate4"):
        report_file = path / "gate_reports" / f"{gate}.{iteration_key(state.current_iteration)}.json"
        if report_file.exists():
            gate_reports[gate] = load_json(report_file)

    score_path = path / "gate_reports" / f"final_scorecard.{iteration_key(state.current_iteration)}.json"
    scorecard = load_json(score_path) if score_path.exists() else None

    report = {
        "run_id": run_id,
        "current_state": state.current_state,
        "current_iteration": state.current_iteration,
        "gate_status": state.gate_status,
        "active_video_provider": state.active_video_provider,
        "latest_direction_pack_id": state.latest_direction_pack_id,
        "latest_image_prompt_package_id": state.latest_image_prompt_package_id,
        "latest_selected_images_id": state.latest_selected_images_id,
        "preprod_locked_iteration": state.preprod_locked_iteration,
        "locked_spec_hash": state.locked_spec_hash,
        "gate_reports": gate_reports,
        "final_scorecard": scorecard,
    }

    out = path / "final_report.json"
    dump_canonical_json(out, report)
    return out
