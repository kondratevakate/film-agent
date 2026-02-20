from __future__ import annotations

from pathlib import Path

from film_agent.replay_inputs import replay_inputs_for_run
from film_agent.state_machine.orchestrator import create_run
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


def _write_full_bundle(target_dir: Path, *, include_direction: bool = True) -> None:
    target_dir.mkdir(parents=True, exist_ok=True)
    write_json(target_dir / "test.script.json", sample_beat_bible())
    if include_direction:
        write_json(target_dir / "test.direction.json", sample_direction())
    write_json(target_dir / "test.dance_mapping.current.json", sample_dance_mapping(direction_pack_id="stale-direction-id"))
    write_json(target_dir / "test.cinematography.json", sample_cinematography(image_prompt_package_id="stale-image-id"))
    write_json(target_dir / "test.audio.current.json", sample_audio_plan("stale-image-id", "stale-selected-id"))
    write_json(
        target_dir / "test.final_metrics.json",
        {
            "videoscore2": 0.9,
            "vbench2_physics": 0.9,
            "identity_drift": 0.1,
            "audiosync_score": 91.0,
            "consistency_score": 90.0,
            "spec_hash": "stale-spec-hash",
            "one_shot_render": True,
        },
    )


def test_replay_inputs_happy_path_reaches_complete(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    run_id = create_run(tmp_path, config).run_id
    _write_full_bundle(tmp_path / "test-film-agent" / "inputs")

    result = replay_inputs_for_run(tmp_path, run_id)

    state = load_state(run_dir(tmp_path, run_id))
    assert state.current_state == "COMPLETE"
    assert result["warnings"] == []
    assert any(action["kind"] == "submit" and action["agent"] == "final_metrics" for action in result["actions"])


def test_replay_inputs_missing_file_warns_and_stops(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    run_id = create_run(tmp_path, config).run_id
    _write_full_bundle(tmp_path / "test-film-agent" / "inputs", include_direction=False)

    result = replay_inputs_for_run(tmp_path, run_id)

    assert result["stopped_reason"] == "missing_direction"
    assert any("Missing input JSON for agent 'direction'" in item for item in result["warnings"])
    submits = [item for item in result["actions"] if item["kind"] == "submit"]
    assert len(submits) == 1
    assert submits[0]["agent"] == "showrunner"

    state = load_state(run_dir(tmp_path, run_id))
    assert state.current_state == "COLLECT_DIRECTION"


def test_replay_inputs_uses_legacy_folder_when_inputs_missing(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    run_id = create_run(tmp_path, config).run_id
    _write_full_bundle(tmp_path / "test-film-agent")

    result = replay_inputs_for_run(tmp_path, run_id)
    state = load_state(run_dir(tmp_path, run_id))

    assert state.current_state == "COMPLETE"
    submit_actions = [item for item in result["actions"] if item["kind"] == "submit"]
    assert submit_actions
    assert all(item["input_root"].endswith("test-film-agent") for item in submit_actions)
