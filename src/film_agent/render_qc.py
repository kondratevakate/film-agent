"""Automated VLM quality checks for rendered shots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from film_agent.io.json_io import dump_canonical_json
from film_agent.providers.video_veo_yunwu import image_path_to_data_uri


@dataclass(frozen=True)
class ShotQcJudgement:
    score: float | None
    reason_codes: list[str]
    summary: str
    judge_available: bool


@dataclass(frozen=True)
class RenderQcResult:
    qc_path: Path
    passed_count: int
    failed_count: int
    retry_count: int


def decide_qc_outcome(
    *,
    score: float | None,
    threshold: float,
    retries_used: int,
    retry_limit: int,
    judge_available: bool,
) -> tuple[str, list[str]]:
    if not judge_available:
        return "fail", ["judge_unavailable"]
    if score is None:
        return "fail", ["missing_score"]
    if score >= threshold:
        return "pass", ["score_above_threshold"]
    if retries_used < retry_limit:
        return "retry", ["score_below_threshold"]
    return "fail", ["score_below_threshold", "retry_limit_reached"]


def judge_shot_quality(
    *,
    api_key: str,
    model: str,
    shot_id: str,
    reference_image_path: Path | None,
    frame_image_path: Path,
    image_prompt: str,
    video_prompt: str,
    audio_prompt: str,
) -> ShotQcJudgement:
    try:
        from openai import OpenAI
    except Exception:
        return ShotQcJudgement(
            score=None,
            reason_codes=["judge_unavailable"],
            summary="openai package is not available.",
            judge_available=False,
        )

    if not api_key.strip():
        return ShotQcJudgement(
            score=None,
            reason_codes=["judge_unavailable"],
            summary="OpenAI API key missing for QC judge.",
            judge_available=False,
        )

    try:
        client = OpenAI(api_key=api_key)
        user_content: list[dict[str, Any]] = [
            {
                "type": "input_text",
                "text": (
                    "Evaluate generated shot quality and return JSON only with fields: "
                    "score (0..1), reason_codes (array of short strings), summary (string).\n\n"
                    f"shot_id: {shot_id}\n"
                    f"image_prompt: {image_prompt}\n"
                    f"video_prompt: {video_prompt}\n"
                    f"audio_prompt: {audio_prompt}\n"
                    "Scoring dimensions: prompt adherence, identity consistency, composition, and artifact severity."
                ),
            }
        ]

        if reference_image_path is not None and reference_image_path.exists():
            user_content.append({"type": "input_text", "text": "Reference image:"})
            user_content.append(
                {
                    "type": "input_image",
                    "image_url": image_path_to_data_uri(reference_image_path),
                }
            )

        user_content.append({"type": "input_text", "text": "Generated frame image:"})
        user_content.append(
            {
                "type": "input_image",
                "image_url": image_path_to_data_uri(frame_image_path),
            }
        )

        response = client.responses.create(
            model=model,
            input=[
                {
                    "role": "system",
                    "content": "You are a strict visual QC judge for cinematic shots. Return valid JSON only.",
                },
                {"role": "user", "content": user_content},
            ],
        )
        text = getattr(response, "output_text", "") or _extract_response_text(response)
        payload = _extract_json_object(text)
        score = _coerce_score(payload.get("score")) if isinstance(payload, dict) else None
        reason_codes = _normalize_reason_codes(payload.get("reason_codes") if isinstance(payload, dict) else None)
        summary = str(payload.get("summary", "")) if isinstance(payload, dict) else ""
        return ShotQcJudgement(
            score=score,
            reason_codes=reason_codes,
            summary=summary.strip(),
            judge_available=True,
        )
    except Exception as exc:  # pragma: no cover - network/runtime behavior
        return ShotQcJudgement(
            score=None,
            reason_codes=["judge_unavailable", "judge_error"],
            summary=str(exc),
            judge_available=False,
        )


def extract_video_frame(video_path: Path, frame_out: Path) -> bool:
    try:
        from moviepy import VideoFileClip
    except Exception:
        return False

    try:
        clip = VideoFileClip(str(video_path))
        t = max(0.0, min(float(getattr(clip, "duration", 0.0) or 0.0) / 2.0, max(float(getattr(clip, "duration", 0.0) or 0.0) - 0.05, 0.0)))
        frame_out.parent.mkdir(parents=True, exist_ok=True)
        clip.save_frame(str(frame_out), t=t)
        clip.close()
        return frame_out.exists()
    except Exception:
        return False


def write_render_qc_report(
    *,
    output_path: Path,
    run_id: str,
    iteration: int,
    threshold: float,
    judge_model: str,
    shots: list[dict[str, Any]],
) -> RenderQcResult:
    failed = [item for item in shots if item.get("decision") == "fail"]
    passed = [item for item in shots if item.get("decision") == "pass"]
    retries = [item for item in shots if item.get("decision") == "retry"]

    payload = {
        "run_id": run_id,
        "iteration": iteration,
        "threshold": threshold,
        "judge_model": judge_model,
        "shots": shots,
        "failed_shots": [item.get("shot_id") for item in failed],
    }
    dump_canonical_json(output_path, payload)
    return RenderQcResult(
        qc_path=output_path,
        passed_count=len(passed),
        failed_count=len(failed),
        retry_count=len(retries),
    )


def _extract_response_text(response: Any) -> str:
    data = response.model_dump() if hasattr(response, "model_dump") else {}
    output = data.get("output", []) if isinstance(data, dict) else []
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if text:
                chunks.append(str(text))
    return "\n".join(chunks)


def _extract_json_object(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for idx, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(cleaned[idx:])
            return obj
        except json.JSONDecodeError:
            continue
    raise ValueError("Could not parse JSON object from judge output.")


def _coerce_score(value: Any) -> float | None:
    try:
        score = float(value)
    except Exception:
        return None
    if score < 0:
        return 0.0
    if score > 1:
        return 1.0
    return score


def _normalize_reason_codes(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out
