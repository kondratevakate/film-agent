"""API render runner for FINAL_RENDER stage artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from math import gcd
from pathlib import Path
from typing import Iterable

from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.io.json_io import dump_canonical_json
from film_agent.providers.video_veo_yunwu import YunwuVeoClient, build_veo_yunwu_video_payload
from film_agent.schemas.artifacts import AVPromptPackage, RenderPackage, SelectedImagesArtifact
from film_agent.state_machine.state_store import iteration_key, load_state, run_dir


SUPPORTED_RENDER_PROVIDERS = {"veo_yunwu", "yunwu_veo", "vimax_veo_yunwu", "veo-yunwu"}


@dataclass(frozen=True)
class RenderApiRunResult:
    run_id: str
    iteration: int
    provider: str
    output_dir: Path
    manifest_path: Path
    generated_count: int


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
    fail_fast: bool = True,
) -> RenderApiRunResult:
    run_path = run_dir(base_dir, run_id)
    state = load_state(run_path)
    iter_key = iteration_key(state.current_iteration)

    audio = load_artifact_for_agent(run_path, state, "audio")
    selected = load_artifact_for_agent(run_path, state, "cinematography")
    render_package = load_artifact_for_agent(run_path, state, "render_package")

    if audio is None:
        raise ValueError("Missing audio artifact for current iteration.")
    if selected is None:
        raise ValueError("Missing cinematography artifact for current iteration.")
    if render_package is None:
        raise ValueError("Missing render_package artifact for current iteration.")

    audio = AVPromptPackage.model_validate(audio)
    selected = SelectedImagesArtifact.model_validate(selected)
    render_package = RenderPackage.model_validate(render_package)

    resolved_provider = (provider or render_package.video_provider).strip().lower()
    if resolved_provider not in SUPPORTED_RENDER_PROVIDERS:
        supported = ", ".join(sorted(SUPPORTED_RENDER_PROVIDERS))
        raise ValueError(f"Unsupported render-api provider '{resolved_provider}'. Supported: {supported}")

    if output_dir is None:
        output_dir = run_path / "iterations" / iter_key / "render_outputs" / "veo_yunwu"
    output_dir.mkdir(parents=True, exist_ok=True)

    reference_map = _build_reference_image_map(selected, run_path=run_path, base_dir=base_dir)
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
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "shots": [],
    }
    shot_rows = manifest["shots"]
    assert isinstance(shot_rows, list)

    generated_count = 0
    client = YunwuVeoClient(api_key=api_key) if not dry_run else None
    first_error: Exception | None = None

    for index, shot in enumerate(audio.shot_prompts, start=1):
        ref = reference_map.get(shot.shot_id)
        prompt = build_video_prompt_text(shot.video_prompt, audio.global_negative_constraints)
        payload = build_veo_yunwu_video_payload(
            prompt=prompt,
            reference_image_paths=[ref] if ref else [],
            model=effective_model,
            aspect_ratio=aspect_ratio,
        )
        output_path = output_dir / f"{index:02d}_{shot.shot_id}.mp4"
        row: dict[str, object] = {
            "shot_id": shot.shot_id,
            "duration_s": shot.duration_s,
            "reference_image_path": str(ref) if ref else None,
            "output_path": str(output_path),
            "status": "pending",
            "request_preview": {
                "model": payload.get("model"),
                "has_reference_images": bool(payload.get("images")),
                "aspect_ratio": payload.get("aspect_ratio"),
            },
        }

        if dry_run:
            row["status"] = "dry_run"
            shot_rows.append(row)
            continue

        try:
            assert client is not None
            task_id = client.create_task(payload)
            result = client.wait_for_completion(
                task_id,
                poll_interval_s=poll_interval_s,
                timeout_s=timeout_s,
            )
            client.download_video(result.video_url, output_path)
            row["status"] = "completed"
            row["task_id"] = task_id
            row["video_url"] = result.video_url
            generated_count += 1
        except Exception as exc:  # pragma: no cover - network behavior
            row["status"] = "failed"
            row["error"] = str(exc)
            if first_error is None:
                first_error = exc
            if fail_fast:
                shot_rows.append(row)
                break
        shot_rows.append(row)

    manifest_path = output_dir / "render_manifest.json"
    dump_canonical_json(manifest_path, manifest)

    if first_error is not None and fail_fast:
        raise RuntimeError(f"Render failed. See manifest: {manifest_path}") from first_error

    return RenderApiRunResult(
        run_id=run_id,
        iteration=state.current_iteration,
        provider=resolved_provider,
        output_dir=output_dir,
        manifest_path=manifest_path,
        generated_count=generated_count,
    )


def _resolve_model(model_override: str | None, render_package: RenderPackage) -> str:
    if model_override and model_override.strip():
        return model_override.strip()
    model_version = render_package.model_version.strip()
    if model_version.lower().startswith("veo"):
        return model_version
    return "veo3.1-fast"


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
