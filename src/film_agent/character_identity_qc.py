"""VLM-based character identity verification for rendered shots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from film_agent.io.json_io import dump_canonical_json
from film_agent.io.response_parsing import extract_json_object, extract_response_text
from film_agent.providers.video_veo_yunwu import image_path_to_data_uri


@dataclass(frozen=True)
class CharacterIdentityJudgement:
    """Result of comparing character in rendered frame against reference portrait."""

    shot_id: str
    character_name: str
    portrait_path: Path | None
    frame_path: Path

    # Scores 0-1 (None if judge unavailable)
    face_similarity: float | None
    clothing_match: float | None
    age_consistency: float | None
    hair_consistency: float | None
    overall_identity_score: float | None

    reason_codes: list[str]
    summary: str
    judge_available: bool


def decide_identity_outcome(
    *,
    overall_score: float | None,
    threshold: float,
    retries_used: int,
    retry_limit: int,
    judge_available: bool = True,
) -> tuple[str, list[str]]:
    """Decide pass/retry/fail based on identity score."""
    if not judge_available:
        return "fail", ["judge_unavailable"]
    if overall_score is None:
        return "fail", ["missing_score"]
    if overall_score >= threshold:
        return "pass", ["identity_verified"]

    # Check for critical failures (completely wrong person)
    if overall_score < 0.4:
        return "fail", ["critical_identity_mismatch"]

    if retries_used < retry_limit:
        return "retry", ["identity_below_threshold"]

    return "fail", ["identity_below_threshold", "retry_limit_reached"]


def judge_character_identity(
    *,
    api_key: str,
    model: str,
    shot_id: str,
    character_name: str,
    character_features: str,
    portrait_image_path: Path | None,
    frame_image_path: Path,
) -> CharacterIdentityJudgement:
    """Compare character in rendered frame against reference portrait using VLM.

    Args:
        api_key: OpenAI API key
        model: VLM model to use (e.g. gpt-4.1-mini)
        shot_id: Shot identifier for logging
        character_name: Name of the character being verified
        character_features: Static + dynamic features description
        portrait_image_path: Path to reference portrait image
        frame_image_path: Path to rendered frame image

    Returns:
        CharacterIdentityJudgement with scores and verdict
    """
    try:
        from openai import OpenAI
    except Exception:
        return CharacterIdentityJudgement(
            shot_id=shot_id,
            character_name=character_name,
            portrait_path=portrait_image_path,
            frame_path=frame_image_path,
            face_similarity=None,
            clothing_match=None,
            age_consistency=None,
            hair_consistency=None,
            overall_identity_score=None,
            reason_codes=["judge_unavailable"],
            summary="openai package not available",
            judge_available=False,
        )

    if not api_key.strip():
        return CharacterIdentityJudgement(
            shot_id=shot_id,
            character_name=character_name,
            portrait_path=portrait_image_path,
            frame_path=frame_image_path,
            face_similarity=None,
            clothing_match=None,
            age_consistency=None,
            hair_consistency=None,
            overall_identity_score=None,
            reason_codes=["judge_unavailable"],
            summary="API key missing",
            judge_available=False,
        )

    if portrait_image_path is None or not portrait_image_path.exists():
        return CharacterIdentityJudgement(
            shot_id=shot_id,
            character_name=character_name,
            portrait_path=portrait_image_path,
            frame_path=frame_image_path,
            face_similarity=None,
            clothing_match=None,
            age_consistency=None,
            hair_consistency=None,
            overall_identity_score=None,
            reason_codes=["portrait_missing"],
            summary="Portrait reference image not available",
            judge_available=False,
        )

    if not frame_image_path.exists():
        return CharacterIdentityJudgement(
            shot_id=shot_id,
            character_name=character_name,
            portrait_path=portrait_image_path,
            frame_path=frame_image_path,
            face_similarity=None,
            clothing_match=None,
            age_consistency=None,
            hair_consistency=None,
            overall_identity_score=None,
            reason_codes=["frame_missing"],
            summary="Rendered frame not available",
            judge_available=False,
        )

    try:
        client = OpenAI(api_key=api_key)

        prompt = f"""Compare the character in the RENDERED FRAME against the REFERENCE PORTRAIT.

CHARACTER TO VERIFY: {character_name}
EXPECTED FEATURES: {character_features}

Analyze and return JSON ONLY with these fields:
{{
    "face_similarity": <float 0.0-1.0>,      // facial features match
    "clothing_match": <float 0.0-1.0>,       // outfit/accessories match
    "age_consistency": <float 0.0-1.0>,      // appears same age (CRITICAL)
    "hair_consistency": <float 0.0-1.0>,     // hairstyle/color match (CRITICAL)
    "overall_identity_score": <float 0.0-1.0>,  // weighted average
    "reason_codes": ["list", "of", "issues"],   // short codes like "wrong_age", "wrong_hair"
    "summary": "brief explanation"
}}

CRITICAL CHECKS (score 0.0 if these fail):
- Is this the SAME PERSON as in the portrait? (not just similar clothing)
- Does age match? (child vs adult is CRITICAL failure = 0.0)
- Does hairstyle match? (ponytail vs curly hair is CRITICAL failure)
- Does clothing match the expected costume/color?

If the character in the frame is clearly a DIFFERENT PERSON, set overall_identity_score to 0.0-0.3.
If minor differences exist but same person, score 0.5-0.8.
If excellent match, score 0.8-1.0."""

        user_content: list[dict[str, Any]] = [
            {"type": "input_text", "text": prompt},
            {"type": "input_text", "text": "REFERENCE PORTRAIT:"},
            {
                "type": "input_image",
                "image_url": image_path_to_data_uri(portrait_image_path),
            },
            {"type": "input_text", "text": "RENDERED FRAME:"},
            {
                "type": "input_image",
                "image_url": image_path_to_data_uri(frame_image_path),
            },
        ]

        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": "You are a character identity verification expert. Compare portraits against rendered frames. Return valid JSON only, no markdown.",
                },
                {"role": "user", "content": user_content},
            ],
        )

        # Extract response text
        raw = extract_response_text(response)
        data = extract_json_object(raw)

        if data is None:
            return CharacterIdentityJudgement(
                shot_id=shot_id,
                character_name=character_name,
                portrait_path=portrait_image_path,
                frame_path=frame_image_path,
                face_similarity=None,
                clothing_match=None,
                age_consistency=None,
                hair_consistency=None,
                overall_identity_score=None,
                reason_codes=["parse_error"],
                summary=f"Failed to parse VLM response: {raw[:200]}",
                judge_available=True,
            )

        return CharacterIdentityJudgement(
            shot_id=shot_id,
            character_name=character_name,
            portrait_path=portrait_image_path,
            frame_path=frame_image_path,
            face_similarity=_safe_float(data.get("face_similarity")),
            clothing_match=_safe_float(data.get("clothing_match")),
            age_consistency=_safe_float(data.get("age_consistency")),
            hair_consistency=_safe_float(data.get("hair_consistency")),
            overall_identity_score=_safe_float(data.get("overall_identity_score")),
            reason_codes=data.get("reason_codes", []),
            summary=str(data.get("summary", "")),
            judge_available=True,
        )

    except Exception as exc:
        return CharacterIdentityJudgement(
            shot_id=shot_id,
            character_name=character_name,
            portrait_path=portrait_image_path,
            frame_path=frame_image_path,
            face_similarity=None,
            clothing_match=None,
            age_consistency=None,
            hair_consistency=None,
            overall_identity_score=None,
            reason_codes=["api_error"],
            summary=str(exc)[:200],
            judge_available=False,
        )


def _safe_float(value: Any) -> float | None:
    """Safely convert value to float, returning None on failure."""
    if value is None:
        return None
    try:
        return float(value)
    except (ValueError, TypeError):
        return None


def write_identity_qc_report(
    *,
    output_path: Path,
    run_id: str,
    iteration: int,
    threshold: float,
    judge_model: str,
    results: list[dict[str, Any]],
    failed_shots: list[str],
) -> Path:
    """Write identity QC report to JSON file."""
    report = {
        "run_id": run_id,
        "iteration": iteration,
        "threshold": threshold,
        "judge_model": judge_model,
        "total_checks": len(results),
        "passed_checks": len([r for r in results if r.get("outcome") == "pass"]),
        "failed_checks": len([r for r in results if r.get("outcome") == "fail"]),
        "results": results,
        "failed_shots": failed_shots,
    }
    dump_canonical_json(output_path, report)
    return output_path
