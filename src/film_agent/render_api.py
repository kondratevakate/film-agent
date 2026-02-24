"""API render runner for FINAL_RENDER stage artifacts."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from math import gcd
from pathlib import Path
from typing import Any, Iterable

from film_agent.io.artifact_store import load_artifact_for_agent

logger = logging.getLogger(__name__)
from film_agent.io.json_io import dump_canonical_json, load_json
from film_agent.providers.video_veo_yunwu import YunwuVeoClient, build_veo_yunwu_video_payload
from film_agent.schemas.artifacts import AVPromptPackage, RenderPackage, SelectedImagesArtifact
from film_agent.state_machine.state_store import iteration_key, load_state, run_dir


SUPPORTED_RENDER_PROVIDERS = {"veo_yunwu", "yunwu_veo", "vimax_veo_yunwu", "veo-yunwu"}


@dataclass(frozen=True)
class ShotRenderSpec:
    shot_id: str
    duration_s: float
    video_prompt: str
    negative_prompt: str
    reference_image_path: Path | None


@dataclass(frozen=True)
class RenderApiRunResult:
    run_id: str
    iteration: int
    provider: str
    output_dir: Path
    manifest_path: Path
    generated_count: int
    failed_count: int
    skipped_count: int = 0


def resolution_to_aspect_ratio(resolution: str) -> str:
    cleaned = resolution.strip().lower().replace(" ", "")
    if "x" not in cleaned:
        return "16:9"
    left, right = cleaned.split("x", maxsplit=1)
    if not left.isdigit() or not right.isdigit():
        return "16:9"
    width = int(left)
    height = int(right)
    if width <= 0 or height <= 0:
        return "16:9"
    factor = gcd(width, height)
    return f"{width // factor}:{height // factor}"


def build_video_prompt_text(video_prompt: str, negative_constraints: Iterable[str]) -> str:
    base = video_prompt.strip()
    negatives = [item.strip() for item in negative_constraints if item.strip()]
    if not negatives:
        return base
    return f"{base}\nAvoid: {'; '.join(negatives)}"


def validate_prompt_with_core(
    prompt: str,
    shot_id: str,
    project_dir: Path | None = None,
) -> tuple[str, list[str]]:
    """
    Validate and optionally process prompt through core ValidationLoop.

    Args:
        prompt: The video prompt to validate
        shot_id: Shot identifier for logging
        project_dir: Optional path to project config dir (for loading world.yaml)

    Returns:
        (processed_prompt, list_of_warnings)
    """
    try:
        from film_agent.core import ValidationLoop

        if project_dir and (project_dir / "world.yaml").exists():
            loop = ValidationLoop.from_project(project_dir)
            results = loop.validate_all(prompt, shot_id)
            warnings = [r.error_message for r in results if not r.is_valid and r.error_message]

            if warnings:
                logger.warning(f"Shot {shot_id} validation warnings: {warnings}")

            return prompt, warnings
    except ImportError:
        logger.debug("core.ValidationLoop not available, skipping validation")
    except Exception as e:
        logger.debug(f"Validation skipped for {shot_id}: {e}")

    return prompt, []


def render_single_shot_once(
    client: YunwuVeoClient,
    *,
    prompt: str,
    reference_image_path: Path | None,
    model: str,
    aspect_ratio: str,
    output_path: Path,
    poll_interval_s: float,
    timeout_s: float,
) -> dict[str, Any]:
    payload = build_veo_yunwu_video_payload(
        prompt=prompt,
        reference_image_paths=[reference_image_path] if reference_image_path else [],
        model=model,
        aspect_ratio=aspect_ratio,
    )
    task_id = client.create_task(payload)
    result = client.wait_for_completion(task_id, poll_interval_s=poll_interval_s, timeout_s=timeout_s)
    client.download_video(result.video_url, output_path)
    return {
        "task_id": task_id,
        "video_url": result.video_url,
        "payload_preview": {
            "model": payload.get("model"),
            "has_reference_images": bool(payload.get("images")),
            "aspect_ratio": payload.get("aspect_ratio"),
        },
    }


def render_run_via_api(
    base_dir: Path,
    run_id: str,
    *,
    api_key: str,
    provider: str | None = None,
    model: str | None = None,
    output_dir: Path | None = None,
    poll_interval_s: float = 2.0,
    timeout_s: float = 900.0,
    dry_run: bool = False,
    fail_fast: bool = False,
    lines_path: Path | None = None,
    shot_retry_limit: int = 2,
    validation_project_dir: Path | None = None,
) -> RenderApiRunResult:
    run_path = run_dir(base_dir, run_id)
    state = load_state(run_path)
    iter_key = iteration_key(state.current_iteration)

    render_package_raw = load_artifact_for_agent(run_path, state, "render_package")
    if render_package_raw is None:
        raise ValueError("Missing render_package artifact for current iteration.")
    render_package = RenderPackage.model_validate(render_package_raw)

    resolved_provider = (provider or render_package.video_provider).strip().lower()
    if resolved_provider not in SUPPORTED_RENDER_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_RENDER_PROVIDERS))
        raise ValueError(f"Unsupported render-api provider '{resolved_provider}'. Supported: {supported}")

    if output_dir is None:
        output_dir = run_path / "iterations" / iter_key / "render_outputs" / "veo_yunwu"
    output_dir.mkdir(parents=True, exist_ok=True)

    specs, source_info = _load_shot_specs(
        base_dir=base_dir,
        run_path=run_path,
        state=state,
        lines_path=lines_path,
    )

    effective_model = _resolve_model(model_override=model, render_package=render_package)
    aspect_ratio = resolution_to_aspect_ratio(render_package.resolution)

    manifest: dict[str, object] = {
        "run_id": run_id,
        "iteration": state.current_iteration,
        "provider": resolved_provider,
        "model": effective_model,
        "resolution": render_package.resolution,
        "aspect_ratio": aspect_ratio,
        "fps": render_package.fps,
        "dry_run": dry_run,
        "shot_retry_limit": shot_retry_limit,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": source_info,
        "shots": [],
    }
    shot_rows = manifest["shots"]
    assert isinstance(shot_rows, list)

    generated_count = 0
    failed_count = 0
    client = YunwuVeoClient(api_key=api_key) if not dry_run else None

    for index, spec in enumerate(specs, start=1):
        output_path = output_dir / f"{index:02d}_{spec.shot_id}.mp4"
        prompt = build_video_prompt_text(spec.video_prompt, [spec.negative_prompt])

        # Validate prompt through core ValidationLoop if project_dir provided
        validation_warnings: list[str] = []
        if validation_project_dir:
            prompt, validation_warnings = validate_prompt_with_core(
                prompt, spec.shot_id, validation_project_dir
            )

        row: dict[str, object] = {
            "shot_id": spec.shot_id,
            "duration_s": spec.duration_s,
            "reference_image_path": str(spec.reference_image_path) if spec.reference_image_path else None,
            "output_path": str(output_path),
            "status": "pending",
            "attempts": [],
            "validation_warnings": validation_warnings,
            "request_preview": {
                "model": effective_model,
                "aspect_ratio": aspect_ratio,
                "has_reference_images": bool(spec.reference_image_path),
            },
        }
        attempts = row["attempts"]
        assert isinstance(attempts, list)

        if dry_run:
            row["status"] = "dry_run"
            attempts.append({"attempt": 1, "status": "dry_run"})
            shot_rows.append(row)
            continue

        success = False
        for attempt in range(1, shot_retry_limit + 2):
            try:
                assert client is not None
                attempt_result = render_single_shot_once(
                    client,
                    prompt=prompt,
                    reference_image_path=spec.reference_image_path,
                    model=effective_model,
                    aspect_ratio=aspect_ratio,
                    output_path=output_path,
                    poll_interval_s=poll_interval_s,
                    timeout_s=timeout_s,
                )
                attempts.append(
                    {
                        "attempt": attempt,
                        "status": "completed",
                        "task_id": attempt_result.get("task_id"),
                        "video_url": attempt_result.get("video_url"),
                    }
                )
                row["status"] = "completed"
                success = True
                generated_count += 1
                break
            except Exception as exc:  # pragma: no cover - network behavior
                attempts.append({"attempt": attempt, "status": "failed", "error": str(exc)})

        if not success:
            row["status"] = "failed"
            failed_count += 1
            if fail_fast:
                shot_rows.append(row)
                break

        shot_rows.append(row)

    manifest_path = output_dir / "render_manifest.json"
    dump_canonical_json(manifest_path, manifest)

    if failed_count > 0 and fail_fast:
        raise RuntimeError(f"Render failed. See manifest: {manifest_path}")

    return RenderApiRunResult(
        run_id=run_id,
        iteration=state.current_iteration,
        provider=resolved_provider,
        output_dir=output_dir,
        manifest_path=manifest_path,
        generated_count=generated_count,
        failed_count=failed_count,
    )


def _resolve_model(model_override: str | None, render_package: RenderPackage) -> str:
    if model_override and model_override.strip():
        return model_override.strip()
    model_version = render_package.model_version.strip()
    if model_version.lower().startswith("veo"):
        return model_version
    return "veo3.1-fast"


def _load_shot_specs(
    *,
    base_dir: Path,
    run_path: Path,
    state,
    lines_path: Path | None,
) -> tuple[list[ShotRenderSpec], dict[str, Any]]:
    iter_dir = run_path / "iterations" / iteration_key(state.current_iteration)
    candidate_lines = lines_path or (iter_dir / "vimax_input" / "vimax_lines.json")
    if candidate_lines.exists():
        payload = load_json(candidate_lines)
        specs = _build_specs_from_vimax_lines(payload)
        return specs, {"type": "vimax_lines", "path": str(candidate_lines)}

    audio = load_artifact_for_agent(run_path, state, "audio")
    selected = load_artifact_for_agent(run_path, state, "cinematography")
    if audio is None:
        raise ValueError("Missing audio artifact for current iteration.")
    if selected is None:
        raise ValueError("Missing cinematography artifact for current iteration.")

    audio = AVPromptPackage.model_validate(audio)
    selected = SelectedImagesArtifact.model_validate(selected)
    reference_map = _build_reference_image_map(selected, run_path=run_path, base_dir=base_dir)

    specs: list[ShotRenderSpec] = []
    for item in audio.shot_prompts:
        specs.append(
            ShotRenderSpec(
                shot_id=item.shot_id,
                duration_s=float(item.duration_s),
                video_prompt=item.video_prompt,
                negative_prompt=", ".join(audio.global_negative_constraints),
                reference_image_path=reference_map.get(item.shot_id),
            )
        )
    return specs, {"type": "audio+cinematography"}


def _build_specs_from_vimax_lines(payload: Any) -> list[ShotRenderSpec]:
    if not isinstance(payload, dict):
        raise ValueError("vimax_lines payload must be a JSON object.")
    lines = payload.get("lines")
    if not isinstance(lines, list) or not lines:
        raise ValueError("vimax_lines payload has no lines.")

    specs: list[ShotRenderSpec] = []
    seen: set[str] = set()
    for row in lines:
        if not isinstance(row, dict):
            continue
        shot_id = str(row.get("shot_id", "")).strip()
        if not shot_id:
            raise ValueError("vimax_lines line missing shot_id")
        if shot_id in seen:
            raise ValueError(f"Duplicate shot_id in vimax_lines: {shot_id}")
        seen.add(shot_id)

        video_prompt = str(row.get("video_prompt", "")).strip() or str(row.get("image_prompt", "")).strip()
        if not video_prompt:
            raise ValueError(f"Shot {shot_id} has empty video_prompt and image_prompt.")

        duration = float(row.get("duration_s", 0.0) or 0.0)
        if duration <= 0:
            raise ValueError(f"Shot {shot_id} must have duration_s > 0.")

        ref_path_raw = row.get("reference_image_path")
        ref_path = Path(str(ref_path_raw)).resolve() if ref_path_raw else None
        if ref_path is not None and not ref_path.exists():
            ref_path = None

        specs.append(
            ShotRenderSpec(
                shot_id=shot_id,
                duration_s=duration,
                video_prompt=video_prompt,
                negative_prompt=str(row.get("negative_prompt", "")).strip(),
                reference_image_path=ref_path,
            )
        )
    return specs


def _build_reference_image_map(
    selected: SelectedImagesArtifact,
    *,
    run_path: Path,
    base_dir: Path,
) -> dict[str, Path]:
    mapping: dict[str, Path] = {}
    for item in selected.selected_images:
        resolved = _resolve_existing_path(item.image_path, run_path=run_path, base_dir=base_dir)
        if resolved:
            mapping[item.shot_id] = resolved
    return mapping


def _resolve_existing_path(raw_path: str, *, run_path: Path, base_dir: Path) -> Path | None:
    candidate = Path(raw_path)
    candidates: list[Path] = []
    if candidate.is_absolute():
        candidates.append(candidate)
    else:
        candidates.append(run_path / candidate)
        candidates.append(base_dir / candidate)
        candidates.append(Path.cwd() / candidate)
    for current in candidates:
        if current.exists():
            return current.resolve()
    return None
