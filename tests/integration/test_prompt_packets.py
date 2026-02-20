from __future__ import annotations

from pathlib import Path

import pytest

from film_agent.io.package_export import package_iteration
from film_agent.prompt_packets import build_prompt_packet
from film_agent.roles import RoleId
from film_agent.state_machine.orchestrator import create_run, run_gate0, submit_agent
from tests.helpers import sample_beat_bible, sample_direction, write_config, write_json


def test_packet_build_reports_missing_inputs(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    run = create_run(tmp_path, config)
    run_gate0(tmp_path, run.run_id)

    with pytest.raises(ValueError) as exc:
        build_prompt_packet(tmp_path, run.run_id, RoleId.DIRECTION)
    assert "Missing inputs" in str(exc.value)


def test_package_iteration_contains_prompt_packets_and_templates(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    run = create_run(tmp_path, config)
    run_gate0(tmp_path, run.run_id)

    show_path = write_json(tmp_path / "showrunner.json", sample_beat_bible())
    submit_agent(tmp_path, run.run_id, "showrunner", show_path)
    direction_path = write_json(tmp_path / "direction.json", sample_direction())
    submit_agent(tmp_path, run.run_id, "direction", direction_path)

    # Build at least one packet for export copying.
    build_prompt_packet(tmp_path, run.run_id, RoleId.DANCE_MAPPING)

    export_dir = package_iteration(tmp_path, run.run_id, iteration=1)
    assert (export_dir / "prompt_packets").exists()
    assert (export_dir / "submission_templates").exists()
    assert (export_dir / "scripts" / "plan_summary.md").exists()
    assert not (export_dir / ".env").exists()
