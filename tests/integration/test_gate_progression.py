from __future__ import annotations

from pathlib import Path

from film_agent.io.json_io import load_json
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


def _advance_to_gate2(tmp_path: Path, *, threshold_overrides: dict[str, float | int] | None = None) -> str:
    config = write_config(tmp_path, threshold_overrides=threshold_overrides)
    run_id = create_run(tmp_path, config).run_id

    result = run_gate0(tmp_path, run_id)
    assert result.state == "COLLECT_SHOWRUNNER"

    result = submit_agent(tmp_path, run_id, "showrunner", write_json(tmp_path / "showrunner.json", sample_beat_bible()))
    assert result.state == "COLLECT_DIRECTION"

    result = submit_agent(tmp_path, run_id, "direction", write_json(tmp_path / "direction.json", sample_direction()))
    assert result.state == "COLLECT_DANCE_MAPPING"

    state = load_state(run_dir(tmp_path, run_id))
    direction_pack_id = state.latest_direction_pack_id
    assert direction_pack_id

    result = submit_agent(
        tmp_path,
        run_id,
        "dance_mapping",
        write_json(tmp_path / "dance_mapping.json", sample_dance_mapping(direction_pack_id)),
    )
    assert result.state == "COLLECT_CINEMATOGRAPHY"

    result = submit_agent(
        tmp_path,
        run_id,
        "cinematography",
        write_json(tmp_path / "cinematography.json", sample_cinematography()),
    )
    assert result.state == "COLLECT_AUDIO"

    result = submit_agent(tmp_path, run_id, "audio", write_json(tmp_path / "audio.json", sample_audio_plan()))
    assert result.state == "GATE1"

    result = validate_gate(tmp_path, run_id, 1)
    assert result.state == "GATE2"

    result = validate_gate(tmp_path, run_id, 2)
    assert result.state == "DRYRUN"

    return run_id


def test_happy_path_reaches_dryrun_with_expected_states(tmp_path: Path) -> None:
    run_id = _advance_to_gate2(tmp_path)
    state = load_state(run_dir(tmp_path, run_id))
    assert state.current_state == "DRYRUN"
    assert state.gate_status["gate0"] == "passed"
    assert state.gate_status["gate1"] == "passed"
    assert state.gate_status["gate2"] == "passed"

    artifacts_dir = run_dir(tmp_path, run_id) / "iterations" / "iter-01" / "artifacts"
    for filename in (
        "beat_bible.json",
        "user_direction_pack.json",
        "dance_mapping_spec.json",
        "shot_design_sheets.json",
        "audio_plan.json",
    ):
        assert (artifacts_dir / filename).exists()


def test_gate3_blocking_issues_switches_to_fallback_provider(tmp_path: Path) -> None:
    run_id = _advance_to_gate2(tmp_path)

    submit_agent(
        tmp_path,
        run_id,
        "dryrun_metrics",
        write_json(
            tmp_path / "dryrun_bad.json",
            {
                "videoscore2": 0.8,
                "vbench2_physics": 0.8,
                "identity_drift": 0.1,
                "blocking_issues": 1,
            },
        ),
    )

    result = validate_gate(tmp_path, run_id, 3)
    assert result.state == "DRYRUN"

    state = load_state(run_dir(tmp_path, run_id))
    assert state.current_iteration == 2
    assert state.current_state == "DRYRUN"
    assert state.active_video_provider == "hugsfield"


def test_gate4_fails_when_final_score_is_below_floor(tmp_path: Path) -> None:
    run_id = _advance_to_gate2(tmp_path, threshold_overrides={"final_score_floor": 80})

    submit_agent(
        tmp_path,
        run_id,
        "dryrun_metrics",
        write_json(
            tmp_path / "dryrun_blocking.json",
            {
                "videoscore2": 0.85,
                "vbench2_physics": 0.85,
                "identity_drift": 0.1,
                "blocking_issues": 1,
            },
        ),
    )
    validate_gate(tmp_path, run_id, 3)

    submit_agent(
        tmp_path,
        run_id,
        "dryrun_metrics",
        write_json(
            tmp_path / "dryrun_ok.json",
            {
                "videoscore2": 0.85,
                "vbench2_physics": 0.85,
                "identity_drift": 0.1,
                "blocking_issues": 0,
            },
        ),
    )
    result_gate3 = validate_gate(tmp_path, run_id, 3)
    assert result_gate3.state == "FINAL_RENDER"

    submit_agent(
        tmp_path,
        run_id,
        "timeline",
        write_json(
            tmp_path / "timeline.json",
            {
                "entries": [
                    {
                        "shot_id": "s1",
                        "start_s": 0.0,
                        "duration_s": 3.0,
                    }
                ]
            },
        ),
    )
    submit_agent(
        tmp_path,
        run_id,
        "render_package",
        write_json(
            tmp_path / "render_package.json",
            {
                "video_provider": "hugsfield",
                "model_version": "hugsfield-v1",
                "seed": 42,
                "sampler_settings": {},
                "resolution": "1920x1080",
                "fps": 24,
                "prompt_template_versions": {},
            },
        ),
    )
    submit_agent(
        tmp_path,
        run_id,
        "final_metrics",
        write_json(
            tmp_path / "final_metrics.json",
            {
                "videoscore2": 0.84,
                "vbench2_physics": 0.84,
                "identity_drift": 0.1,
                "audiosync_score": 90.0,
                "consistency_score": 85.0,
            },
        ),
    )

    result = validate_gate(tmp_path, run_id, 4)
    assert result.state == "FAILED"
    report = load_json(Path(result.detail["report"]))
    assert "Final score below acceptance floor." in report["reasons"]

    state = load_state(run_dir(tmp_path, run_id))
    assert state.current_state == "FAILED"
