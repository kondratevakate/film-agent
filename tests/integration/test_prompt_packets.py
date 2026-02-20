from __future__ import annotations

import json
from pathlib import Path

import pytest

from film_agent.io.package_export import package_iteration
from film_agent.prompt_packets import build_prompt_packet
from film_agent.roles import RoleId
from film_agent.state_machine.orchestrator import create_run, run_gate0, submit_agent, validate_gate
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
    validate_gate(tmp_path, run.run_id, 1)
    direction_path = write_json(tmp_path / "direction.json", sample_direction())
    submit_agent(tmp_path, run.run_id, "direction", direction_path)

    # Build at least one packet for export copying.
    build_prompt_packet(tmp_path, run.run_id, RoleId.DANCE_MAPPING)

    export_dir = package_iteration(tmp_path, run.run_id, iteration=1)
    assert (export_dir / "prompt_packets").exists()
    assert (export_dir / "submission_templates").exists()
    assert (export_dir / "scripts" / "plan_summary.md").exists()
    assert not (export_dir / ".env").exists()


def test_showrunner_packet_includes_previous_gate1_report_on_retry(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    run = create_run(tmp_path, config)
    run_gate0(tmp_path, run.run_id)

    # Force Gate1 failure to start iteration 2.
    show_path = write_json(tmp_path / "showrunner_bad.json", sample_beat_bible(critical=True))
    submit_agent(tmp_path, run.run_id, "showrunner", show_path)
    validate_gate(tmp_path, run.run_id, 1)

    packet_path, _ = build_prompt_packet(tmp_path, run.run_id, RoleId.SHOWRUNNER, iteration=2)
    packet_text = packet_path.read_text(encoding="utf-8")
    assert "gate1_report" in packet_text
    assert "previous_showrunner_script" in packet_text
    assert "story_anchor" in packet_text
    assert "anchor_showrunner_script" in packet_text


def test_showrunner_packet_includes_configured_look_and_feel_files(tmp_path: Path) -> None:
    config_dir = tmp_path / "config_root"
    style_dir = config_dir / "the-trace"
    ref_dir = config_dir / "refs"
    style_dir.mkdir(parents=True)
    ref_dir.mkdir(parents=True)
    (style_dir / "creative-direction.md").write_text("cinematic grammar check", encoding="utf-8")
    (style_dir / "principles.md").write_text("consistency principles check", encoding="utf-8")
    (style_dir / "tokens.css").write_text(":root { --accent: #D11F2E; }", encoding="utf-8")
    (ref_dir / "a.jpg").write_bytes(b"a")
    (ref_dir / "b.jpg").write_bytes(b"b")

    config = {
        "project_name": "look-and-feel-check",
        "reference_images": [
            {"id": "ref_a", "path": "refs/a.jpg", "tags": ["hallway"], "notes": "hallway baseline"},
            {"id": "ref_b", "path": "refs/b.jpg", "tags": ["gym"], "notes": "gym baseline"},
        ],
        "creative_direction_file": "the-trace/creative-direction.md",
        "principles_file": "the-trace/principles.md",
        "tokens_css_file": "the-trace/tokens.css",
        "duration_target_s": 95,
        "model_candidates": [
            {
                "name": "test-model",
                "weighted_score": 1.0,
                "physics": 1.0,
                "human_fidelity": 1.0,
                "identity": 1.0,
            }
        ],
    }
    config_path = config_dir / "project.yaml"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    run = create_run(tmp_path, config_path)
    run_gate0(tmp_path, run.run_id)

    packet_path, _ = build_prompt_packet(tmp_path, run.run_id, RoleId.SHOWRUNNER, iteration=1)
    packet_text = packet_path.read_text(encoding="utf-8")
    assert "cinematic grammar check" in packet_text
    assert "consistency principles check" in packet_text
    assert "--accent: #D11F2E" in packet_text
    assert "reference_image_catalog" in packet_text
    assert "ref_a" in packet_text
