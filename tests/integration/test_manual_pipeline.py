from __future__ import annotations

import json
from pathlib import Path

import pytest

from film_agent.io.json_io import load_json
from film_agent.io.package_export import package_iteration
from film_agent.state_machine.orchestrator import create_run, run_gate0, submit_agent, validate_gate
from film_agent.state_machine.state_store import load_state, run_dir
from tests.helpers import (
    sample_beat_bible,
    sample_dance_mapping,
    sample_direction,
    write_config,
    write_json,
)


def test_missing_direction_blocks_mapping_submission(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    created = create_run(tmp_path, config)
    run_id = created.run_id
    run_gate0(tmp_path, run_id)

    showrunner_file = write_json(tmp_path / "showrunner.json", sample_beat_bible())
    submit_agent(tmp_path, run_id, "showrunner", showrunner_file)
    validate_gate(tmp_path, run_id, 1)

    dance_file = write_json(
        tmp_path / "dance_mapping.json",
        sample_dance_mapping(direction_pack_id="not-available"),
    )
    with pytest.raises(ValueError):
        submit_agent(tmp_path, run_id, "dance_mapping", dance_file)


def test_direction_update_reflected_in_gate_and_export(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    run_id = create_run(tmp_path, config).run_id
    run_gate0(tmp_path, run_id)

    # Iteration 1 (intentional Gate1 fail due script placeholder markers)
    submit_agent(tmp_path, run_id, "showrunner", write_json(tmp_path / "showrunner_1.json", sample_beat_bible(critical=True)))

    result_gate1_fail = validate_gate(tmp_path, run_id, 1)
    assert result_gate1_fail.state == "COLLECT_SHOWRUNNER"

    # Iteration 2 (update direction and pass Gate1)
    submit_agent(tmp_path, run_id, "showrunner", write_json(tmp_path / "showrunner_2.json", sample_beat_bible(critical=False)))
    result_gate1_pass = validate_gate(tmp_path, run_id, 1)
    assert result_gate1_pass.state == "COLLECT_DIRECTION"

    submit_agent(tmp_path, run_id, "direction", write_json(tmp_path / "direction_2.json", sample_direction(["staccato"])))

    state2 = load_state(run_dir(tmp_path, run_id))
    direction_id_2 = state2.latest_direction_pack_id
    assert direction_id_2
    result_gate2_pass = validate_gate(tmp_path, run_id, 2)
    assert result_gate2_pass.state == "COLLECT_DANCE_MAPPING"

    gate_report_path = run_dir(tmp_path, run_id) / "gate_reports" / "gate1.iter-02.json"
    assert gate_report_path.exists()
    gate_report = load_json(gate_report_path)
    assert gate_report["metrics"]["duration_ok"] is True

    export_dir = package_iteration(tmp_path, run_id, iteration=2)
    direction_export = load_json(export_dir / "artifacts" / "script_review.json")
    assert "staccato" in direction_export["revision_notes"]

    readable_index = (export_dir / "readable_index.md").read_text(encoding="utf-8")
    assert "artifacts/script_review.json" in readable_index


def test_story_anchor_created_and_gate1_blocks_retry_drift(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    run_id = create_run(tmp_path, config).run_id
    run_gate0(tmp_path, run_id)

    submit_agent(tmp_path, run_id, "showrunner", write_json(tmp_path / "showrunner_1.json", sample_beat_bible(critical=True)))
    anchor_path = run_dir(tmp_path, run_id) / "iterations" / "iter-01" / "artifacts" / "story_anchor.json"
    assert anchor_path.exists()
    anchor = load_json(anchor_path)
    assert anchor["title"] == "Test Film"

    validate_gate(tmp_path, run_id, 1)

    drifted = sample_beat_bible(critical=False)
    drifted["title"] = "Different Film"
    drifted["characters"] = ["Narrator", "Other Lead"]
    submit_agent(tmp_path, run_id, "showrunner", write_json(tmp_path / "showrunner_2.json", drifted))
    result = validate_gate(tmp_path, run_id, 1)
    report = load_json(Path(result.detail["report"]))

    assert result.state == "COLLECT_SHOWRUNNER"
    assert any("title" in reason.lower() for reason in report["reasons"])
    assert any("character" in reason.lower() for reason in report["reasons"])
