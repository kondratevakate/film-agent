from __future__ import annotations

import pytest
from pydantic import ValidationError

from film_agent.gates.scoring import compute_dance_mapping_score
from film_agent.schemas.artifacts import BeatBible, DanceMappingSpec, UserDirectionPack


def test_user_direction_pack_strict_validation() -> None:
    with pytest.raises(ValidationError):
        UserDirectionPack.model_validate(
            {
                "iteration_goal": "test",
                "style_references": [],
                "must_include": [],
                "avoid": [],
                "notes": "",
            }
        )


def test_dance_mapping_requires_direction_pack_id() -> None:
    with pytest.raises(ValidationError):
        DanceMappingSpec.model_validate(
            {
                "mappings": [
                    {
                        "beat_id": "b1",
                        "motion_description": "move",
                        "symbolism": "symbol",
                        "motif_tag": "m",
                        "contrast_pattern": "c",
                    }
                ]
            }
        )


def test_dance_score_changes_with_direction_pack() -> None:
    beat_bible = BeatBible.model_validate(
        {
            "concept_thesis": "test",
            "beats": [
                {
                    "beat_id": "b1",
                    "start_s": 0,
                    "end_s": 10,
                    "science_claim": "claim",
                    "dance_metaphor": "metaphor",
                    "visual_motif": "ring",
                    "emotion_intention": "focus",
                    "spoken_line": None,
                    "success_criteria": "clear",
                    "science_status": "ok",
                }
            ],
        }
    )
    mapping = DanceMappingSpec.model_validate(
        {
            "direction_pack_id": "abc",
            "mappings": [
                {
                    "beat_id": "b1",
                    "motion_description": "spiral arm wave",
                    "symbolism": "uncertainty",
                    "motif_tag": "spiral",
                    "contrast_pattern": "stillness to burst",
                }
            ],
        }
    )
    direction_good = UserDirectionPack.model_validate(
        {
            "iteration_goal": "good",
            "style_references": ["contemporary"],
            "must_include": ["spiral"],
            "avoid": ["acrobatics"],
            "notes": "",
        }
    )
    direction_bad = UserDirectionPack.model_validate(
        {
            "iteration_goal": "bad",
            "style_references": ["contemporary"],
            "must_include": ["staccato"],
            "avoid": ["spiral"],
            "notes": "",
        }
    )

    good_score = compute_dance_mapping_score(beat_bible, mapping, direction_good)
    bad_score = compute_dance_mapping_score(beat_bible, mapping, direction_bad)
    assert good_score > bad_score
