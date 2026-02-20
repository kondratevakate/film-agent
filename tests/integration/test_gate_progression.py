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


def _advance_to_post_gate3(tmp_path: Path, *, threshold_overrides: dict[str, float | int] | None = None) -> str:
    config = write_config(tmp_path, threshold_overrides=threshold_overrides)
    run_id = create_run(tmp_path, config).run_id

    result = run_gate0(tmp_path, run_id)
    assert result.state == "COLLECT_SHOWRUNNER"

    result = submit_agent(tmp_path, run_id, "showrunner", write_json(tmp_path / "showrunner.json", sample_beat_bible()))
    assert result.state == "GATE1"

    result = validate_gate(tmp_path, run_id, 1)
    assert result.state == "COLLECT_DIRECTION"

    result = submit_agent(tmp_path, run_id, "direction", write_json(tmp_path / "direction.json", sample_direction()))
    assert result.state == "GATE2"

    result = validate_gate(tmp_path, run_id, 2)
    assert result.state == "COLLECT_DANCE_MAPPING"

    state_before_mapping = load_state(run_dir(tmp_path, run_id))
    direction_pack_id = state_before_mapping.latest_direction_pack_id
    assert direction_pack_id
    result = submit_agent(
        tmp_path,
        run_id,
        "dance_mapping",
        write_json(tmp_path / "dance_mapping.json", sample_dance_mapping(direction_pack_id)),
    )
    assert result.state == "GATE3"

    result = validate_gate(tmp_path, run_id, 3)
    assert result.state == "COLLECT_CINEMATOGRAPHY"

    return run_id


def test_happy_path_reaches_final_render_with_expected_states(tmp_path: Path) -> None:
    run_id = _advance_to_post_gate3(tmp_path)
    state = load_state(run_dir(tmp_path, run_id))
    assert state.current_state == "COLLECT_CINEMATOGRAPHY"
    assert state.gate_status["gate0"] == "passed"
    assert state.gate_status["gate1"] == "passed"
    assert state.gate_status["gate2"] == "passed"
    assert state.gate_status["gate3"] == "passed"

    artifacts_dir = run_dir(tmp_path, run_id) / "iterations" / "iter-01" / "artifacts"
    for filename in (
        "script.json",
        "script_review.json",
        "image_prompt_package.json",
    ):
        assert (artifacts_dir / filename).exists()

    image_prompt_package_id = state.latest_image_prompt_package_id
    assert image_prompt_package_id
    result = submit_agent(
        tmp_path,
        run_id,
        "cinematography",
        write_json(tmp_path / "selected_images.json", sample_cinematography(image_prompt_package_id)),
    )
    assert result.state == "COLLECT_AUDIO"

    state = load_state(run_dir(tmp_path, run_id))
    selected_images_id = state.latest_selected_images_id
    image_prompt_package_id = state.latest_image_prompt_package_id
    assert selected_images_id and image_prompt_package_id
    result = submit_agent(
        tmp_path,
        run_id,
        "audio",
        write_json(tmp_path / "av_prompts.json", sample_audio_plan(image_prompt_package_id, selected_images_id)),
    )
    assert result.state == "FINAL_RENDER"

    state = load_state(run_dir(tmp_path, run_id))
    assert state.locked_spec_hash


def test_gate3_failure_rolls_back_to_image_prompts_iteration(tmp_path: Path) -> None:
    config = write_config(tmp_path)
    run_id = create_run(tmp_path, config).run_id
    run_gate0(tmp_path, run_id)
    submit_agent(tmp_path, run_id, "showrunner", write_json(tmp_path / "showrunner.json", sample_beat_bible()))
    validate_gate(tmp_path, run_id, 1)
    submit_agent(tmp_path, run_id, "direction", write_json(tmp_path / "direction.json", sample_direction()))
    validate_gate(tmp_path, run_id, 2)

    state = load_state(run_dir(tmp_path, run_id))
    direction_pack_id = state.latest_direction_pack_id
    assert direction_pack_id
    bad_mapping = sample_dance_mapping(direction_pack_id)
    bad_mapping["image_prompts"] = bad_mapping["image_prompts"][:2]
    submit_agent(tmp_path, run_id, "dance_mapping", write_json(tmp_path / "bad_mapping.json", bad_mapping))

    result = validate_gate(tmp_path, run_id, 3)
    assert result.state == "COLLECT_DANCE_MAPPING"

    state = load_state(run_dir(tmp_path, run_id))
    assert state.current_iteration == 2
    assert state.current_state == "COLLECT_DANCE_MAPPING"


def test_gate4_fails_when_final_score_is_below_floor(tmp_path: Path) -> None:
    run_id = _advance_to_post_gate3(tmp_path, threshold_overrides={"final_score_floor": 99})
    state = load_state(run_dir(tmp_path, run_id))
    image_prompt_package_id = state.latest_image_prompt_package_id
    assert image_prompt_package_id
    submit_agent(
        tmp_path,
        run_id,
        "cinematography",
        write_json(
            tmp_path / "selected_images.json",
            sample_cinematography(image_prompt_package_id),
        ),
    )
    state = load_state(run_dir(tmp_path, run_id))
    selected_images_id = state.latest_selected_images_id
    image_prompt_package_id = state.latest_image_prompt_package_id
    assert selected_images_id and image_prompt_package_id
    submit_agent(
        tmp_path,
        run_id,
        "audio",
        write_json(
            tmp_path / "av_prompts.json",
            sample_audio_plan(image_prompt_package_id, selected_images_id),
        ),
    )

    state = load_state(run_dir(tmp_path, run_id))
    spec_hash = state.locked_spec_hash or ""
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
                "spec_hash": spec_hash,
                "one_shot_render": True,
            },
        ),
    )

    result = validate_gate(tmp_path, run_id, 4)
    assert result.state == "FAILED"
    report = load_json(Path(result.detail["report"]))
    assert "Final score below acceptance floor." in report["reasons"]

    state = load_state(run_dir(tmp_path, run_id))
    assert state.current_state == "FAILED"
