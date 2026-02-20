from __future__ import annotations

import json
from pathlib import Path

from film_agent.io.json_io import dump_canonical_json


def write_config(
    path: Path,
    core_concepts: list[str] | None = None,
    threshold_overrides: dict[str, float | int] | None = None,
) -> Path:
    thresholds = {
        "gate0_physics_floor": 0.7,
        "gate0_human_fidelity_floor": 0.7,
        "gate0_identity_floor": 0.7,
        "videoscore2_threshold": 0.7,
        "vbench2_physics_floor": 0.7,
        "identity_drift_ceiling": 0.2,
        "regression_epsilon": 0.08,
        "shot_variety_min_types": 3,
        "max_consecutive_identical_framing": 2,
        "variety_score_threshold": 70,
        "final_score_floor": 70,
    }
    if threshold_overrides:
        thresholds.update(threshold_overrides)

    payload = {
        "project_name": "test-film-agent",
        "duration_target_s": 95,
        "core_concepts": core_concepts or [],
        "seed": 42,
        "resolution": "1920x1080",
        "fps": 24,
        "providers": {
            "audio": "elevenlabs",
            "image_primary": "openai_images",
            "image_secondary": "nanobanana",
            "video_primary": "sora",
            "video_fallback": "hugsfield",
        },
        "model_candidates": [
            {
                "name": "openai-video-prod",
                "weighted_score": 0.9,
                "physics": 0.9,
                "human_fidelity": 0.9,
                "identity": 0.9,
            }
        ],
        "thresholds": thresholds,
        "retry_limits": {"gate1": 3, "gate2": 3, "gate3": 2},
    }
    out = path / "config.yaml"
    out.write_text(json.dumps(payload), encoding="utf-8")
    return out


def write_json(path: Path, payload: dict) -> Path:
    dump_canonical_json(path, payload)
    return path


def sample_beat_bible(critical: bool = False) -> dict:
    lines = []
    for idx in range(12):
        kind = "dialogue" if idx % 3 == 0 else "action"
        speaker = "Narrator" if kind == "dialogue" else None
        text = "TODO placeholder" if critical and idx == 0 else f"Story line {idx + 1}"
        lines.append(
            {
                "line_id": f"l{idx+1}",
                "kind": kind,
                "text": text,
                "speaker": speaker,
                "est_duration_s": 8.0,
            }
        )
    return {
        "title": "Test Film",
        "logline": "A compact narrative for testing gates.",
        "theme": "consistency under constraints",
        "characters": ["Narrator", "Lead"],
        "locations": ["stage-a", "hallway"],
        "lines": lines,
    }


def sample_direction(must_include: list[str] | None = None) -> dict:
    return {
        "script_version": 1,
        "script_hash_hint": "script-v1",
        "approved_story_facts": [
            "Lead enters stage and delivers a focused narrative.",
            "No additional characters are introduced.",
        ],
        "approved_character_registry": ["Narrator", "Lead"],
        "revision_notes": must_include or ["tighten opening action"],
        "unresolved_items": [],
        "lock_story_facts": True,
    }


def sample_dance_mapping(direction_pack_id: str) -> dict:
    prompts = []
    for idx in range(5):
        prompts.append(
            {
                "shot_id": f"s{idx+1}",
                "intent": "clear character action with stable framing",
                "image_prompt": (
                    f"Shot s{idx+1}: cinematic still of Lead in stage-a, "
                    "single action, grounded movement, realistic lighting"
                ),
                "negative_prompt": "blurry, deformed face, extra limbs",
                "duration_s": 5.0,
            }
        )
    return {"script_review_id": direction_pack_id, "style_anchor": "clean kinetic realism", "image_prompts": prompts}


def sample_cinematography(image_prompt_package_id: str) -> dict:
    return {
        "image_prompt_package_id": image_prompt_package_id,
        "selected_images": [
            {
                "shot_id": "s1",
                "image_path": "images/s1.png",
                "image_sha256": "a" * 64,
                "notes": "good identity match",
            },
            {
                "shot_id": "s2",
                "image_path": "images/s2.png",
                "image_sha256": "b" * 64,
                "notes": "strong composition",
            },
            {
                "shot_id": "s3",
                "image_path": "images/s3.png",
                "image_sha256": "c" * 64,
                "notes": "usable for transition",
            },
        ],
    }


def sample_audio_plan(image_prompt_package_id: str, selected_images_id: str) -> dict:
    return {
        "image_prompt_package_id": image_prompt_package_id,
        "selected_images_id": selected_images_id,
        "music_prompt": "subtle cinematic pulse with sparse rhythm",
        "shot_prompts": [
            {
                "shot_id": "s1",
                "video_prompt": "Start with a medium shot of Lead, single deliberate gesture.",
                "audio_prompt": "light ambience with soft impact accent",
                "tts_text": "We begin in uncertainty.",
                "duration_s": 5.0,
            },
            {
                "shot_id": "s2",
                "video_prompt": "Cut to close-up preserving facial identity and lighting.",
                "audio_prompt": "brief swell and quiet bed",
                "tts_text": "Then attention tightens.",
                "duration_s": 5.0,
            },
            {
                "shot_id": "s3",
                "video_prompt": "Wide resolve shot, stable direction and smooth motion.",
                "audio_prompt": "resolve tone and tail",
                "tts_text": "Finally the pattern resolves.",
                "duration_s": 5.0,
            },
        ],
        "global_negative_constraints": ["identity drift", "camera teleport"],
    }
