from __future__ import annotations

import json
from pathlib import Path

import pytest

from film_agent.io.json_io import load_json
from film_agent.io.package_export import package_iteration
from film_agent.state_machine.orchestrator import create_run, run_gate0, submit_agent, validate_gate
from film_agent.state_machine.state_store import load_state, run_dir
from tests.helpers import (
    sample_audio_plan,
    sample_beat_bible,
    sample_cinematography,
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

    # Iteration 1 (intentional Gate1 fail due critical science error)
    submit_agent(tmp_path, run_id, "showrunner", write_json(tmp_path / "showrunner_1.json", sample_beat_bible(critical=True)))
    submit_agent(tmp_path, run_id, "direction", write_json(tmp_path / "direction_1.json", sample_direction(["spiral"])))

    state1 = load_state(run_dir(tmp_path, run_id))
    direction_id_1 = state1.latest_direction_pack_id
    assert direction_id_1

    submit_agent(
        tmp_path,
        run_id,
        "dance_mapping",
        write_json(tmp_path / "dance_1.json", sample_dance_mapping(direction_id_1)),
    )
    submit_agent(tmp_path, run_id, "cinematography", write_json(tmp_path / "cin_1.json", sample_cinematography()))
    submit_agent(tmp_path, run_id, "audio", write_json(tmp_path / "audio_1.json", sample_audio_plan()))

    result_gate1_fail = validate_gate(tmp_path, run_id, 1)
    assert result_gate1_fail.state == "COLLECT_SHOWRUNNER"

    # Iteration 2 (update direction and pass Gate1)
    submit_agent(tmp_path, run_id, "showrunner", write_json(tmp_path / "showrunner_2.json", sample_beat_bible(critical=False)))
    submit_agent(tmp_path, run_id, "direction", write_json(tmp_path / "direction_2.json", sample_direction(["staccato"])))

    state2 = load_state(run_dir(tmp_path, run_id))
    direction_id_2 = state2.latest_direction_pack_id
    assert direction_id_2
    assert direction_id_2 != direction_id_1

    submit_agent(
        tmp_path,
        run_id,
        "dance_mapping",
        write_json(tmp_path / "dance_2.json", sample_dance_mapping(direction_id_2)),
    )
    submit_agent(tmp_path, run_id, "cinematography", write_json(tmp_path / "cin_2.json", sample_cinematography()))
    submit_agent(tmp_path, run_id, "audio", write_json(tmp_path / "audio_2.json", sample_audio_plan()))

    result_gate1_pass = validate_gate(tmp_path, run_id, 1)
    assert result_gate1_pass.state == "GATE2"

    gate_report_path = run_dir(tmp_path, run_id) / "gate_reports" / "gate1.iter-02.json"
    assert gate_report_path.exists()
    gate_report = load_json(gate_report_path)
    assert gate_report["metrics"]["direction_pack_id"] == direction_id_2

    export_dir = package_iteration(tmp_path, run_id, iteration=2)
    direction_export = load_json(export_dir / "artifacts" / "user_direction_pack.json")
    assert "staccato" in direction_export["must_include"]

    readable_index = (export_dir / "readable_index.md").read_text(encoding="utf-8")
    assert "artifacts/user_direction_pack.json" in readable_index
