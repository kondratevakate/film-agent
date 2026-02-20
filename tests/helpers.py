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
    beats = []
    start = 0.0
    for idx in range(9):
        end = start + 10.0
        beats.append(
            {
                "beat_id": f"b{idx+1}",
                "start_s": start,
                "end_s": end,
                "science_claim": f"concept-{idx+1}",
                "dance_metaphor": f"move-{idx+1}",
                "visual_motif": "ring",
                "emotion_intention": "focus",
                "spoken_line": None,
                "success_criteria": "clear mapping",
                "science_status": "critical_error" if critical and idx == 0 else "ok",
            }
        )
        start = end
    return {
        "concept_thesis": "I will explain X by dancing Y because Z.",
        "beats": beats,
    }


def sample_direction(must_include: list[str] | None = None) -> dict:
    return {
        "iteration_goal": "Lean into grounded contemporary style.",
        "style_references": ["Pina Bausch", "minimal staging"],
        "must_include": must_include or ["spiral"],
        "avoid": ["acrobatics"],
        "notes": "User-defined direction for this iteration.",
    }


def sample_dance_mapping(direction_pack_id: str) -> dict:
    mappings = []
    for idx in range(9):
        mappings.append(
            {
                "beat_id": f"b{idx+1}",
                "motion_description": "spiral arm sweep with grounded footwork",
                "symbolism": "represents uncertainty and integration",
                "motif_tag": "spiral",
                "contrast_pattern": "stillness to burst",
            }
        )
    return {"direction_pack_id": direction_pack_id, "mappings": mappings}


def sample_cinematography() -> dict:
    return {
        "character_bank": {
            "characters": [
                {
                    "name": "Lead",
                    "identity_token": "lead-v1",
                    "costume_style_constraints": ["white shirt"],
                    "forbidden_drift_rules": ["no mask"],
                }
            ]
        },
        "shots": [
            {
                "shot_id": "s1",
                "beat_id": "b1",
                "character": "Lead",
                "identity_token": "lead-v1",
                "background": "studio",
                "pose_action": "opening stance",
                "props": [],
                "camera": "dolly in",
                "framing": "wide",
                "lighting": "soft key",
                "style_constraints": ["minimal"],
                "duration_s": 3.0,
                "location": "stage-a",
                "continuity_reset": False,
            },
            {
                "shot_id": "s2",
                "beat_id": "b1",
                "character": "Lead",
                "identity_token": "lead-v1",
                "background": "studio",
                "pose_action": "turn",
                "props": [],
                "camera": "static",
                "framing": "medium",
                "lighting": "soft key",
                "style_constraints": ["minimal"],
                "duration_s": 3.0,
                "location": "stage-a",
                "continuity_reset": False,
            },
            {
                "shot_id": "s3",
                "beat_id": "b2",
                "character": "Lead",
                "identity_token": "lead-v1",
                "background": "studio",
                "pose_action": "close expression",
                "props": [],
                "camera": "handheld",
                "framing": "close",
                "lighting": "backlight",
                "style_constraints": ["minimal"],
                "duration_s": 3.0,
                "location": "stage-a",
                "continuity_reset": False,
            },
        ],
    }


def sample_audio_plan() -> dict:
    return {
        "motifs": ["pulse"],
        "voice_lines": [
            {"line_id": "l1", "timestamp_s": 5.0, "speaker": "Narrator", "text": "This is a line."}
        ],
        "cues": [
            {
                "cue_id": "c1",
                "timestamp_s": 0.0,
                "duration_s": 20.0,
                "cue_type": "music",
                "description": "intro pulse",
            }
        ],
        "sync_markers": [0.0, 5.0, 10.0],
    }
