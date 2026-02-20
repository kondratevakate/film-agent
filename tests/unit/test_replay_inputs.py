from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from film_agent.replay_inputs import patch_payload_links, select_input_file


def test_select_input_file_prefers_current_variant(tmp_path: Path) -> None:
    base = tmp_path / "the_trace.audio.json"
    current = tmp_path / "the_trace.audio.current.json"
    base.write_text("{}", encoding="utf-8")
    current.write_text("{}", encoding="utf-8")

    selected = select_input_file([base, current], prefer_current=True)
    assert selected == current


def test_select_input_file_prefers_base_when_requested(tmp_path: Path) -> None:
    base = tmp_path / "the_trace.audio.json"
    current = tmp_path / "the_trace.audio.current.json"
    base.write_text("{}", encoding="utf-8")
    current.write_text("{}", encoding="utf-8")

    selected = select_input_file([base, current], prefer_current=False)
    assert selected == base


def test_patch_payload_links_updates_expected_ids() -> None:
    state = SimpleNamespace(
        latest_direction_pack_id="direction-id",
        latest_image_prompt_package_id="image-id",
        latest_selected_images_id="selected-id",
        locked_spec_hash="spec-hash",
    )

    dance = patch_payload_links(
        agent="dance_mapping",
        payload={"script_review_id": "stale", "style_anchor": "x", "image_prompts": []},
        state=state,
    )
    assert dance["script_review_id"] == "direction-id"

    cinematography = patch_payload_links(
        agent="cinematography",
        payload={"image_prompt_package_id": "stale", "selected_images": []},
        state=state,
    )
    assert cinematography["image_prompt_package_id"] == "image-id"

    audio = patch_payload_links(
        agent="audio",
        payload={
            "image_prompt_package_id": "stale",
            "selected_images_id": "stale",
            "music_prompt": "m",
            "shot_prompts": [],
        },
        state=state,
    )
    assert audio["image_prompt_package_id"] == "image-id"
    assert audio["selected_images_id"] == "selected-id"

    final_metrics = patch_payload_links(
        agent="final_metrics",
        payload={
            "videoscore2": 0.9,
            "vbench2_physics": 0.9,
            "identity_drift": 0.1,
            "audiosync_score": 90,
            "consistency_score": 90,
            "spec_hash": "stale",
        },
        state=state,
    )
    assert final_metrics["spec_hash"] == "spec-hash"
    assert final_metrics["one_shot_render"] is True
