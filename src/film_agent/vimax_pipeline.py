"""End-to-end ViMax bridge pipeline: prepare -> render -> auto QC -> final mix."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from film_agent.final_mix import FinalMixResult, build_final_mix

logger = logging.getLogger(__name__)
from film_agent.io.json_io import dump_canonical_json, load_json
from film_agent.render_api import (
    build_video_prompt_text,
    render_run_via_api,
    render_single_shot_once,
)
from film_agent.render_qc import (
    decide_qc_outcome,
    extract_video_frame,
    judge_shot_quality,
    write_render_qc_report,
)
from film_agent.character_identity_qc import (
    CharacterIdentityJudgement,
    decide_identity_outcome,
    judge_character_identity,
    write_identity_qc_report,
)
from film_agent.providers.video_veo_yunwu import YunwuVeoClient
from film_agent.state_machine.state_store import load_state, run_dir
from film_agent.vimax_bridge import VimaxPrepareResult, prepare_vimax_inputs


@dataclass(frozen=True)
class VimaxPipelineRunResult:
    run_id: str
    iteration: int
    vimax_input_dir: Path
    render_manifest_path: Path
    render_qc_path: Path
    final_video_path: Path
    final_mix_manifest_path: Path
    failed_shots: list[str]


def run_vimax_pipeline(
    base_dir: Path,
    run_id: str,
    *,
    openai_api_key: str,
    yunwu_api_key: str,
    anchor_images: list[str],
    image_model: str = "gpt-image-1",
    qc_model: str = "gpt-4.1-mini",
    qc_threshold: float = 0.75,
    identity_qc_enabled: bool = True,
    identity_qc_threshold: float = 0.75,
    identity_qc_critical: float = 0.40,
    shot_retry_limit: int = 2,
    poll_interval_s: float = 2.0,
    timeout_s: float = 900.0,
    pipeline_timeout_s: float = 14400.0,  # 4 hours default
    tts_model: str = "gpt-4o-mini-tts",
    tts_voice: str = "alloy",
    dry_run: bool = False,
    progress_callback: Callable[[str, int, int], None] | None = None,
) -> VimaxPipelineRunResult:
    prepared = prepare_vimax_inputs(
        base_dir,
        run_id,
        api_key=openai_api_key,
        image_model=image_model,
        dry_run=dry_run,
        anchor_images=anchor_images,
        required_anchor_count=5,
    )

    render_result = render_run_via_api(
        base_dir,
        run_id,
        api_key=yunwu_api_key,
        lines_path=prepared.lines_path,
        dry_run=dry_run,
        fail_fast=False,
        shot_retry_limit=shot_retry_limit,
        poll_interval_s=poll_interval_s,
        timeout_s=timeout_s,
    )

    if dry_run:
        state = load_state(run_dir(base_dir, run_id))
        qc_path = render_result.output_dir / "render_qc.json"
        dump_canonical_json(
            qc_path,
            {
                "run_id": run_id,
                "iteration": state.current_iteration,
                "threshold": qc_threshold,
                "identity_qc_enabled": identity_qc_enabled,
                "identity_qc_threshold": identity_qc_threshold,
                "judge_model": qc_model,
                "shots": [],
                "failed_shots": [],
                "dry_run": True,
            },
        )
        mix_result = build_final_mix(
            run_id=run_id,
            iteration=state.current_iteration,
            lines_path=prepared.lines_path,
            render_manifest_path=render_result.manifest_path,
            render_qc_path=qc_path,
            output_dir=render_result.output_dir / "final_mix",
            openai_api_key=openai_api_key,
            tts_model=tts_model,
            tts_voice=tts_voice,
            dry_run=True,
        )
        return VimaxPipelineRunResult(
            run_id=run_id,
            iteration=state.current_iteration,
            vimax_input_dir=prepared.output_dir,
            render_manifest_path=render_result.manifest_path,
            render_qc_path=qc_path,
            final_video_path=mix_result.output_video_path,
            final_mix_manifest_path=mix_result.manifest_path,
            failed_shots=[],
        )

    state = load_state(run_dir(base_dir, run_id))
    lines_payload = load_json(prepared.lines_path)
    lines = lines_payload.get("lines") if isinstance(lines_payload, dict) else None
    if not isinstance(lines, list):
        raise ValueError("Invalid vimax_lines payload.")

    manifest = load_json(render_result.manifest_path)
    if not isinstance(manifest, dict):
        raise ValueError("Invalid render manifest payload.")
    shot_rows = manifest.get("shots")
    if not isinstance(shot_rows, list):
        raise ValueError("Render manifest missing shots list.")

    model = str(manifest.get("model", "veo3.1-fast"))
    aspect_ratio = str(manifest.get("aspect_ratio", "16:9"))
    client = YunwuVeoClient(api_key=yunwu_api_key)

    qc_rows: list[dict[str, Any]] = []
    pipeline_start_time = time.time()
    total_shots = len([line for line in lines if isinstance(line, dict) and str(line.get("shot_id", "")).strip()])

    for idx, line in enumerate(lines, start=1):
        # Check pipeline timeout
        elapsed = time.time() - pipeline_start_time
        if elapsed >= pipeline_timeout_s:
            logger.warning(
                f"Pipeline timeout reached after {elapsed:.1f}s. "
                f"Processed {idx - 1}/{total_shots} shots."
            )
            break
        if not isinstance(line, dict):
            continue
        shot_id = str(line.get("shot_id", "")).strip()
        if not shot_id:
            continue

        render_row = _find_render_row(shot_rows, shot_id)
        if render_row is None:
            qc_rows.append(
                {
                    "shot_id": shot_id,
                    "score": None,
                    "decision": "fail",
                    "retries_used": 0,
                    "reason_codes": ["missing_render_row"],
                    "summary": "Shot missing in render manifest.",
                }
            )
            continue

        retries_used = 0
        final_judgement: dict[str, Any] | None = None

        while True:
            # Check pipeline timeout inside retry loop
            if time.time() - pipeline_start_time >= pipeline_timeout_s:
                final_judgement = {
                    "shot_id": shot_id,
                    "score": None,
                    "decision": "fail",
                    "retries_used": retries_used,
                    "reason_codes": ["pipeline_timeout"],
                    "summary": "Pipeline timeout reached during QC retry loop.",
                }
                break

            output_path = Path(str(render_row.get("output_path", "")))
            if not output_path.exists() or str(render_row.get("status")) != "completed":
                if retries_used < shot_retry_limit:
                    _rerender_shot(
                        client=client,
                        render_row=render_row,
                        line=line,
                        model=model,
                        aspect_ratio=aspect_ratio,
                        poll_interval_s=poll_interval_s,
                        timeout_s=timeout_s,
                    )
                    retries_used += 1
                    continue
                final_judgement = {
                    "shot_id": shot_id,
                    "score": None,
                    "decision": "fail",
                    "retries_used": retries_used,
                    "reason_codes": ["render_failed", "retry_limit_reached"],
                    "summary": "Render output missing or failed.",
                }
                break

            frame_path = render_result.output_dir / "qc_frames" / f"{idx:02d}_{shot_id}.png"
            has_frame = extract_video_frame(output_path, frame_path)
            if not has_frame:
                if retries_used < shot_retry_limit:
                    _rerender_shot(
                        client=client,
                        render_row=render_row,
                        line=line,
                        model=model,
                        aspect_ratio=aspect_ratio,
                        poll_interval_s=poll_interval_s,
                        timeout_s=timeout_s,
                    )
                    retries_used += 1
                    continue
                final_judgement = {
                    "shot_id": shot_id,
                    "score": None,
                    "decision": "fail",
                    "retries_used": retries_used,
                    "reason_codes": ["frame_extraction_failed", "retry_limit_reached"],
                    "summary": "Could not extract a QC frame from rendered video.",
                }
                break

            reference_path = _safe_path(line.get("reference_image_path"))
            judgement = judge_shot_quality(
                api_key=openai_api_key,
                model=qc_model,
                shot_id=shot_id,
                reference_image_path=reference_path,
                frame_image_path=frame_path,
                image_prompt=str(line.get("image_prompt", "")),
                video_prompt=str(line.get("video_prompt", "")),
                audio_prompt=str(line.get("audio_prompt", "")),
            )
            decision, reason_codes = decide_qc_outcome(
                score=judgement.score,
                threshold=qc_threshold,
                retries_used=retries_used,
                retry_limit=shot_retry_limit,
                judge_available=judgement.judge_available,
            )

            if decision == "retry":
                _rerender_shot(
                    client=client,
                    render_row=render_row,
                    line=line,
                    model=model,
                    aspect_ratio=aspect_ratio,
                    poll_interval_s=poll_interval_s,
                    timeout_s=timeout_s,
                )
                retries_used += 1
                continue

            # Character identity QC (after render quality passes)
            identity_result: dict[str, Any] | None = None
            if identity_qc_enabled and decision == "pass":
                characters = line.get("visible_characters", [])
                for char_info in characters:
                    if not isinstance(char_info, dict):
                        continue
                    char_name = str(char_info.get("name", ""))
                    char_features = str(char_info.get("features", ""))
                    portrait_path = _safe_path(char_info.get("portrait_path"))

                    if not char_name or portrait_path is None:
                        continue

                    id_judgement = judge_character_identity(
                        api_key=openai_api_key,
                        model=qc_model,
                        shot_id=shot_id,
                        character_name=char_name,
                        character_features=char_features,
                        portrait_image_path=portrait_path,
                        frame_image_path=frame_path,
                    )

                    id_decision, id_reason = decide_identity_outcome(
                        overall_score=id_judgement.overall_identity_score,
                        threshold=identity_qc_threshold,
                        retries_used=retries_used,
                        retry_limit=shot_retry_limit,
                        judge_available=id_judgement.judge_available,
                    )

                    identity_result = {
                        "character": char_name,
                        "score": id_judgement.overall_identity_score,
                        "face_similarity": id_judgement.face_similarity,
                        "clothing_match": id_judgement.clothing_match,
                        "age_consistency": id_judgement.age_consistency,
                        "hair_consistency": id_judgement.hair_consistency,
                        "decision": id_decision,
                        "reason_codes": id_reason + id_judgement.reason_codes,
                        "summary": id_judgement.summary,
                    }

                    # Critical identity failure (completely wrong person)
                    if id_judgement.overall_identity_score is not None:
                        if id_judgement.overall_identity_score < identity_qc_critical:
                            decision = "fail"
                            reason_codes = ["critical_identity_mismatch"] + reason_codes
                            logger.warning(
                                f"Shot {shot_id}: Critical identity mismatch for {char_name} "
                                f"(score {id_judgement.overall_identity_score:.2f} < {identity_qc_critical})"
                            )
                            break

                    if id_decision == "retry":
                        _rerender_shot(
                            client=client,
                            render_row=render_row,
                            line=line,
                            model=model,
                            aspect_ratio=aspect_ratio,
                            poll_interval_s=poll_interval_s,
                            timeout_s=timeout_s,
                        )
                        retries_used += 1
                        break  # break from character loop, continue main loop

                # If we triggered a retry from identity QC, continue the main loop
                if identity_result and identity_result.get("decision") == "retry":
                    continue

            final_judgement = {
                "shot_id": shot_id,
                "score": judgement.score,
                "decision": decision,
                "retries_used": retries_used,
                "reason_codes": reason_codes + judgement.reason_codes,
                "summary": judgement.summary,
                "output_path": str(output_path),
                "frame_path": str(frame_path),
            }
            if identity_result:
                final_judgement["identity_qc"] = identity_result
            break

        assert final_judgement is not None
        qc_rows.append(final_judgement)

        # Log progress
        logger.info(
            f"Shot {idx}/{total_shots} ({shot_id}): {final_judgement.get('decision', 'unknown')} "
            f"(retries: {retries_used}, elapsed: {time.time() - pipeline_start_time:.1f}s)"
        )
        if progress_callback is not None:
            progress_callback(shot_id, idx, total_shots)

    # persist any rerender updates
    dump_canonical_json(render_result.manifest_path, manifest)

    qc_path = render_result.output_dir / "render_qc.json"
    qc_result = write_render_qc_report(
        output_path=qc_path,
        run_id=run_id,
        iteration=state.current_iteration,
        threshold=qc_threshold,
        judge_model=qc_model,
        shots=qc_rows,
    )

    mix_result: FinalMixResult = build_final_mix(
        run_id=run_id,
        iteration=state.current_iteration,
        lines_path=prepared.lines_path,
        render_manifest_path=render_result.manifest_path,
        render_qc_path=qc_result.qc_path,
        output_dir=render_result.output_dir / "final_mix",
        openai_api_key=openai_api_key,
        tts_model=tts_model,
        tts_voice=tts_voice,
        dry_run=False,
    )

    failed_shots = [str(item.get("shot_id")) for item in qc_rows if str(item.get("decision")) == "fail"]
    return VimaxPipelineRunResult(
        run_id=run_id,
        iteration=state.current_iteration,
        vimax_input_dir=prepared.output_dir,
        render_manifest_path=render_result.manifest_path,
        render_qc_path=qc_result.qc_path,
        final_video_path=mix_result.output_video_path,
        final_mix_manifest_path=mix_result.manifest_path,
        failed_shots=failed_shots,
    )


def _find_render_row(rows: list[dict[str, Any]], shot_id: str) -> dict[str, Any] | None:
    for row in rows:
        if str(row.get("shot_id", "")).strip() == shot_id:
            return row
    return None


def _safe_path(raw: Any) -> Path | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    path = Path(raw)
    if path.exists():
        return path
    return None


def _rerender_shot(
    *,
    client: YunwuVeoClient,
    render_row: dict[str, Any],
    line: dict[str, Any],
    model: str,
    aspect_ratio: str,
    poll_interval_s: float,
    timeout_s: float,
) -> None:
    output_path = Path(str(render_row.get("output_path", "")))
    prompt = build_video_prompt_text(
        str(line.get("video_prompt") or line.get("image_prompt") or ""),
        [str(line.get("negative_prompt", ""))],
    )
    reference = _safe_path(line.get("reference_image_path"))

    attempts = render_row.get("attempts")
    if not isinstance(attempts, list):
        attempts = []
        render_row["attempts"] = attempts
    attempt_number = len(attempts) + 1

    try:
        result = render_single_shot_once(
            client,
            prompt=prompt,
            reference_image_path=reference,
            model=model,
            aspect_ratio=aspect_ratio,
            output_path=output_path,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
        )
        attempts.append(
            {
                "attempt": attempt_number,
                "status": "completed",
                "task_id": result.get("task_id"),
                "video_url": result.get("video_url"),
                "reason": "qc_retry",
            }
        )
        render_row["status"] = "completed"
    except Exception as exc:  # pragma: no cover - network behavior
        attempts.append(
            {
                "attempt": attempt_number,
                "status": "failed",
                "error": str(exc),
                "reason": "qc_retry",
            }
        )
        render_row["status"] = "failed"
