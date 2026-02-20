from __future__ import annotations

from film_agent.schemas.artifacts import AVPromptPackage, ImagePromptPackage
from film_agent.vimax_bridge import (
    build_reference_prompt,
    build_vimax_lines,
    suggest_openai_image_size,
    validate_vimax_lines,
)


def test_build_vimax_lines_merges_dance_and_audio() -> None:
    dance = ImagePromptPackage.model_validate(
        {
            "script_review_id": "x",
            "style_anchor": "clean cinematic realism",
            "image_prompts": [
                {
                    "shot_id": "s1",
                    "intent": "opening shot",
                    "image_prompt": "Wide shot of lead in corridor",
                    "negative_prompt": "blur",
                    "duration_s": 4.0,
                },
                {
                    "shot_id": "s2",
                    "intent": "close reaction",
                    "image_prompt": "Close-up on lead face",
                    "negative_prompt": "",
                    "duration_s": 5.0,
                },
            ],
        }
    )
    audio = AVPromptPackage.model_validate(
        {
            "image_prompt_package_id": "ip",
            "selected_images_id": "si",
            "music_prompt": "soft pulse",
            "shot_prompts": [
                {
                    "shot_id": "s1",
                    "video_prompt": "Push in to lead",
                    "audio_prompt": "room tone",
                    "tts_text": "We start here.",
                    "duration_s": 6.0,
                },
                {
                    "shot_id": "s3",
                    "video_prompt": "Cut to object insert",
                    "audio_prompt": "light hit",
                    "tts_text": None,
                    "duration_s": 3.0,
                },
            ],
            "global_negative_constraints": [],
        }
    )

    rows = build_vimax_lines(dance=dance, audio=audio)

    assert [row["shot_id"] for row in rows] == ["s1", "s2", "s3"]
    assert rows[0]["duration_s"] == 6.0
    assert rows[1]["video_prompt"] == ""
    assert rows[2]["intent"] == "derived_from_video_prompt"


def test_build_reference_prompt_contains_constraints() -> None:
    prompt = build_reference_prompt(
        image_prompt="Character stands in frame center.",
        negative_prompt="extra fingers",
        style_anchor="neo-noir realism",
        video_prompt="Camera dolly in.",
        anchor_records=[
            {"anchor_id": "A01", "path": "anchors/a.png", "sha256": "x", "name": "a.png"},
            {"anchor_id": "A02", "path": "anchors/b.png", "sha256": "y", "name": "b.png"},
        ],
        shot_id="s1",
    )
    assert "Style anchor: neo-noir realism" in prompt
    assert "Shot context: Camera dolly in." in prompt
    assert "Avoid: extra fingers" in prompt
    assert "Anchor A01:" in prompt


def test_suggest_openai_image_size() -> None:
    assert suggest_openai_image_size("1920x1080") == "1536x1024"
    assert suggest_openai_image_size("1080x1920") == "1024x1536"
    assert suggest_openai_image_size("1000x1000") == "1024x1024"
    assert suggest_openai_image_size("bad") == "1536x1024"


def test_validate_vimax_lines_reports_duration_conflicts() -> None:
    payload = [
        {
            "shot_id": "s1",
            "duration_s": 3.0,
            "image_prompt": "A",
            "video_prompt": "B",
            "duration_conflict": True,
        },
        {
            "shot_id": "s2",
            "duration_s": 4.0,
            "image_prompt": "A2",
            "video_prompt": "",
            "duration_conflict": False,
        },
    ]
    report = validate_vimax_lines(payload)
    assert report["line_count"] == 2
    assert report["duration_conflicts"] == ["s1"]
