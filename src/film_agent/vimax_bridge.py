"""Build ViMax-ready line package and reference images from run artifacts."""

from __future__ import annotations

import base64
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import re
from typing import Any
from urllib.request import urlopen

logger = logging.getLogger(__name__)

from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.io.hashing import sha256_file, sha256_json
from film_agent.io.json_io import dump_canonical_json, load_json
from film_agent.schemas.artifacts import AVPromptPackage, ImagePromptPackage, RenderPackage
from film_agent.state_machine.state_store import iteration_key, load_state, run_dir


@dataclass(frozen=True)
class VimaxPrepareResult:
    run_id: str
    iteration: int
    output_dir: Path
    references_dir: Path
    lines_path: Path
    manifest_path: Path
    planned_lines: int
    generated_references: int
    reused_references: int
    anchor_count: int


def prepare_vimax_inputs(
    base_dir: Path,
    run_id: str,
    *,
    api_key: str,
    image_model: str = "gpt-image-1",
    image_size: str | None = None,
    output_dir: Path | None = None,
    dry_run: bool = False,
    force_regenerate: bool = False,
    anchor_images: list[str] | None = None,
    required_anchor_count: int = 5,
) -> VimaxPrepareResult:
    run_path = run_dir(base_dir, run_id)
    state = load_state(run_path)
    iter_key = iteration_key(state.current_iteration)

    dance = load_artifact_for_agent(run_path, state, "dance_mapping")
    if dance is None:
        raise ValueError("Missing dance_mapping artifact for current iteration.")
    dance = ImagePromptPackage.model_validate(dance)

    audio_raw = load_artifact_for_agent(run_path, state, "audio")
    if audio_raw is None:
        raise ValueError("Missing audio artifact for current iteration.")
    audio = AVPromptPackage.model_validate(audio_raw)

    render_raw = load_artifact_for_agent(run_path, state, "render_package")
    render_package = RenderPackage.model_validate(render_raw) if render_raw is not None else None

    lines = build_vimax_lines(dance=dance, audio=audio)
    validation = validate_vimax_lines(lines)
    final_size = image_size or suggest_openai_image_size(render_package.resolution if render_package else None)

    out_dir = output_dir or (run_path / "iterations" / iter_key / "vimax_input")
    refs_dir = out_dir / "reference_images"
    refs_dir.mkdir(parents=True, exist_ok=True)

    anchors = _resolve_anchor_images(
        anchor_images=anchor_images,
        state_reference_images=state.reference_images,
        run_path=run_path,
        base_dir=base_dir,
        required_count=required_anchor_count,
    )
    anchor_records = _build_anchor_records(anchors)

    cache_path = out_dir / "reference_cache.json"
    cache = _load_reference_cache(cache_path)

    generated = 0
    reused = 0

    client = _build_openai_client(api_key=api_key) if not dry_run else None
    rows: list[dict[str, Any]] = []
    shot_anchor_trace: list[dict[str, Any]] = []
    generation_tasks: list[dict[str, Any]] = []

    # Phase 1: Prepare all rows and collect generation tasks
    for index, line in enumerate(lines, start=1):
        shot_id = str(line["shot_id"])
        refined_prompt = build_reference_prompt(
            image_prompt=str(line.get("image_prompt", "")),
            negative_prompt=str(line.get("negative_prompt", "")),
            style_anchor=str(dance.style_anchor),
            video_prompt=str(line.get("video_prompt", "")),
            anchor_records=anchor_records,
            shot_id=shot_id,
        )

        prompt_hash = sha256_json(
            {
                "shot_id": shot_id,
                "prompt": refined_prompt,
                "image_model": image_model,
                "image_size": final_size,
                "anchors": [{"anchor_id": a["anchor_id"], "sha256": a["sha256"]} for a in anchor_records],
            }
        )
        filename = f"{index:02d}_{_slugify(shot_id)}_{prompt_hash[:10]}.png"
        target = refs_dir / filename

        row = dict(line)
        row["reference_prompt"] = refined_prompt
        row["prompt_hash"] = prompt_hash
        row["reference_image_path"] = str(target)
        row["image_size"] = final_size
        row["image_model"] = image_model
        row["anchor_trace"] = [a["anchor_id"] for a in anchor_records]

        cached = cache.get(shot_id)
        if cached and cached.get("prompt_hash") == prompt_hash:
            cached_path = Path(str(cached.get("path", "")))
            if cached_path.exists() and not force_regenerate:
                row["reference_image_path"] = str(cached_path)
                row["reference_status"] = "reused_cache"
                reused += 1
                rows.append(row)
                shot_anchor_trace.append(_build_shot_anchor_trace(row, anchor_records))
                continue

        if target.exists() and not force_regenerate:
            row["reference_status"] = "reused_file"
            reused += 1
            cache[shot_id] = {
                "prompt_hash": prompt_hash,
                "path": str(target),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            rows.append(row)
            shot_anchor_trace.append(_build_shot_anchor_trace(row, anchor_records))
            continue

        if dry_run:
            row["reference_status"] = "planned"
            rows.append(row)
            shot_anchor_trace.append(_build_shot_anchor_trace(row, anchor_records))
            continue

        # Queue for parallel generation
        row["reference_status"] = "pending"
        rows.append(row)
        shot_anchor_trace.append(_build_shot_anchor_trace(row, anchor_records))
        generation_tasks.append({
            "row_index": len(rows) - 1,
            "shot_id": shot_id,
            "prompt": refined_prompt,
            "target": target,
            "prompt_hash": prompt_hash,
        })

    # Phase 2: Parallel image generation
    if generation_tasks and client is not None:
        max_workers = min(5, len(generation_tasks))  # Limit concurrent requests
        logger.info(f"Generating {len(generation_tasks)} images in parallel (max_workers={max_workers})")

        def generate_single(task: dict[str, Any]) -> tuple[dict[str, Any], bytes]:
            image_bytes = _generate_openai_image_bytes(
                client=client,
                model=image_model,
                prompt=task["prompt"],
                size=final_size,
            )
            return task, image_bytes

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {executor.submit(generate_single, task): task for task in generation_tasks}
            for future in as_completed(futures):
                task = futures[future]
                try:
                    _, image_bytes = future.result()
                    task["target"].write_bytes(image_bytes)

                    # Update row status
                    row_idx = task["row_index"]
                    rows[row_idx]["reference_status"] = "generated"
                    generated += 1

                    # Update cache
                    cache[task["shot_id"]] = {
                        "prompt_hash": task["prompt_hash"],
                        "path": str(task["target"]),
                        "updated_at": datetime.now(timezone.utc).isoformat(),
                    }
                    logger.debug(f"Generated image for shot {task['shot_id']}")
                except Exception as e:
                    logger.error(f"Failed to generate image for shot {task['shot_id']}: {e}")
                    row_idx = task["row_index"]
                    rows[row_idx]["reference_status"] = "failed"
                    rows[row_idx]["error"] = str(e)

    lines_payload = {
        "run_id": run_id,
        "iteration": state.current_iteration,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "anchors": anchor_records,
        "music_prompt": audio.music_prompt,
        "global_negative_constraints": audio.global_negative_constraints,
        "lines": rows,
    }
    lines_path = out_dir / "vimax_lines.json"
    dump_canonical_json(lines_path, lines_payload)

    _write_lines_markdown(out_dir / "vimax_lines.md", rows)
    _write_lines_text(out_dir / "vimax_lines.txt", rows)
    dump_canonical_json(out_dir / "anchor_trace.json", {"anchors": anchor_records, "shots": shot_anchor_trace})
    dump_canonical_json(cache_path, cache)

    manifest = {
        "run_id": run_id,
        "iteration": state.current_iteration,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "image_model": image_model,
        "image_size": final_size,
        "planned_lines": len(rows),
        "generated_references": generated,
        "reused_references": reused,
        "anchor_count": len(anchor_records),
        "validation": validation,
    }
    manifest_path = out_dir / "manifest.json"
    dump_canonical_json(manifest_path, manifest)

    return VimaxPrepareResult(
        run_id=run_id,
        iteration=state.current_iteration,
        output_dir=out_dir,
        references_dir=refs_dir,
        lines_path=lines_path,
        manifest_path=manifest_path,
        planned_lines=len(rows),
        generated_references=generated,
        reused_references=reused,
        anchor_count=len(anchor_records),
    )


def build_vimax_lines(*, dance: ImagePromptPackage, audio: AVPromptPackage) -> list[dict[str, Any]]:
    audio_by_shot = {item.shot_id: item for item in audio.shot_prompts}
    out: list[dict[str, Any]] = []
    seen: set[str] = set()

    for item in dance.image_prompts:
        shot_audio = audio_by_shot.get(item.shot_id)
        duration_conflict = False
        if shot_audio is not None:
            duration_conflict = abs(float(shot_audio.duration_s) - float(item.duration_s)) > 1e-6
        out.append(
            {
                "shot_id": item.shot_id,
                "duration_s": shot_audio.duration_s if shot_audio else item.duration_s,
                "duration_source": "audio" if shot_audio else "dance_mapping",
                "duration_conflict": duration_conflict,
                "image_prompt": item.image_prompt,
                "negative_prompt": item.negative_prompt,
                "video_prompt": shot_audio.video_prompt if shot_audio else "",
                "audio_prompt": shot_audio.audio_prompt if shot_audio else "",
                "tts_text": shot_audio.tts_text if shot_audio else None,
                "intent": item.intent,
            }
        )
        seen.add(item.shot_id)

    for shot in audio.shot_prompts:
        if shot.shot_id in seen:
            continue
        out.append(
            {
                "shot_id": shot.shot_id,
                "duration_s": shot.duration_s,
                "duration_source": "audio",
                "duration_conflict": False,
                "image_prompt": shot.video_prompt,
                "negative_prompt": "",
                "video_prompt": shot.video_prompt,
                "audio_prompt": shot.audio_prompt,
                "tts_text": shot.tts_text,
                "intent": "derived_from_video_prompt",
            }
        )
    return out


def validate_vimax_lines(lines: list[dict[str, Any]]) -> dict[str, Any]:
    duplicates: list[str] = []
    seen: set[str] = set()
    empty_prompts: list[str] = []
    duration_conflicts: list[str] = []

    for row in lines:
        shot_id = str(row.get("shot_id", "")).strip()
        if not shot_id:
            raise ValueError("Each line must define a non-empty shot_id.")
        if shot_id in seen:
            duplicates.append(shot_id)
        seen.add(shot_id)

        image_prompt = str(row.get("image_prompt", "")).strip()
        video_prompt = str(row.get("video_prompt", "")).strip()
        if not image_prompt and not video_prompt:
            empty_prompts.append(shot_id)

        duration = float(row.get("duration_s", 0.0) or 0.0)
        if duration <= 0:
            raise ValueError(f"Shot {shot_id}: duration_s must be > 0.")

        if bool(row.get("duration_conflict")):
            duration_conflicts.append(shot_id)

    if duplicates:
        ordered = sorted(set(duplicates))
        raise ValueError(f"Duplicate shot_id values detected: {ordered}")
    if empty_prompts:
        raise ValueError(f"Missing image/video prompts for shot_ids: {sorted(empty_prompts)}")

    return {
        "line_count": len(lines),
        "duration_conflicts": sorted(duration_conflicts),
        "duration_conflicts_count": len(duration_conflicts),
    }


def build_reference_prompt(
    *,
    image_prompt: str,
    negative_prompt: str,
    style_anchor: str,
    video_prompt: str,
    anchor_records: list[dict[str, Any]],
    shot_id: str,
) -> str:
    parts: list[str] = [f"Shot ID: {shot_id}", image_prompt.strip()]
    if style_anchor.strip():
        parts.append(f"Style anchor: {style_anchor.strip()}")
    if video_prompt.strip():
        parts.append(f"Shot context: {video_prompt.strip()}")

    if anchor_records:
        anchor_text = "\n".join(
            f"Anchor {item['anchor_id']}: keep identity/style consistent with {Path(str(item['path'])).name}."
            for item in anchor_records
        )
        parts.append(anchor_text)

    if negative_prompt.strip():
        parts.append(f"Avoid: {negative_prompt.strip()}")
    return "\n".join(item for item in parts if item)


def suggest_openai_image_size(resolution: str | None) -> str:
    if not resolution:
        return "1536x1024"
    cleaned = resolution.strip().lower().replace(" ", "")
    if "x" not in cleaned:
        return "1536x1024"
    left, right = cleaned.split("x", maxsplit=1)
    if not (left.isdigit() and right.isdigit()):
        return "1536x1024"
    width = int(left)
    height = int(right)
    if width <= 0 or height <= 0:
        return "1536x1024"
    ratio = width / height
    if ratio >= 1.25:
        return "1536x1024"
    if ratio <= 0.8:
        return "1024x1536"
    return "1024x1024"


def _resolve_anchor_images(
    *,
    anchor_images: list[str] | None,
    state_reference_images: list[str],
    run_path: Path,
    base_dir: Path,
    required_count: int,
) -> list[Path]:
    raw_paths = anchor_images or state_reference_images
    resolved: list[Path] = []

    for item in raw_paths:
        p = _resolve_existing_path(item, run_path=run_path, base_dir=base_dir)
        if p is None:
            raise ValueError(f"Anchor image not found: {item}")
        resolved.append(p)

    # keep unique by absolute string while preserving order
    uniq: list[Path] = []
    seen: set[str] = set()
    for p in resolved:
        key = str(p)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(p)

    if len(uniq) < required_count:
        raise ValueError(
            f"Need {required_count} anchor images, got {len(uniq)}. "
            "Pass --anchor-image exactly 5 times or provide 5 config reference_images."
        )
    if len(uniq) > required_count:
        uniq = uniq[:required_count]
    return uniq


def _build_anchor_records(anchors: list[Path]) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for idx, path in enumerate(anchors, start=1):
        records.append(
            {
                "anchor_id": f"A{idx:02d}",
                "path": str(path),
                "sha256": sha256_file(path),
                "name": path.name,
            }
        )
    return records


def _build_shot_anchor_trace(row: dict[str, Any], anchor_records: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "shot_id": row.get("shot_id"),
        "prompt_hash": row.get("prompt_hash"),
        "anchor_ids": [a["anchor_id"] for a in anchor_records],
        "reference_image_path": row.get("reference_image_path"),
    }


def _load_reference_cache(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    payload = load_json(path)
    if not isinstance(payload, dict):
        return {}
    normalized: dict[str, dict[str, Any]] = {}
    for key, value in payload.items():
        if isinstance(key, str) and isinstance(value, dict):
            normalized[key] = value
    return normalized


def _resolve_existing_path(raw_path: str | Path, *, run_path: Path, base_dir: Path) -> Path | None:
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


def _build_openai_client(*, api_key: str):
    if not api_key.strip():
        raise ValueError("Missing api_key for reference generation.")
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - runtime dependency issue
        raise RuntimeError("openai package is required.") from exc
    return OpenAI(api_key=api_key)


def _generate_openai_image_bytes(*, client, model: str, prompt: str, size: str) -> bytes:
    response = client.images.generate(model=model, prompt=prompt, size=size)
    data = getattr(response, "data", None) or []
    if not data:
        raise RuntimeError("Image API returned no data.")
    item = data[0]
    b64 = _get_data_field(item, "b64_json")
    if isinstance(b64, str) and b64.strip():
        return base64.b64decode(b64)
    url = _get_data_field(item, "url")
    if isinstance(url, str) and url.strip():
        with urlopen(url) as handle:  # noqa: S310 (URL comes from trusted API response)
            return handle.read()
    raise RuntimeError(f"Image API response has neither b64_json nor url: {_safe_item_repr(item)}")


def _get_data_field(item: Any, key: str) -> Any:
    if isinstance(item, dict):
        return item.get(key)
    return getattr(item, key, None)


def _safe_item_repr(item: Any) -> str:
    if hasattr(item, "model_dump"):
        return json.dumps(item.model_dump(), ensure_ascii=True)
    if isinstance(item, dict):
        return json.dumps(item, ensure_ascii=True)
    return repr(item)


def _slugify(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9_-]+", "-", value).strip("-")
    return cleaned or "shot"


def _write_lines_markdown(path: Path, rows: list[dict[str, Any]]) -> None:
    lines = ["# ViMax Lines", ""]
    for row in rows:
        lines.append(f"## {row['shot_id']}")
        lines.append(f"- duration_s: {row.get('duration_s')}")
        lines.append(f"- duration_source: {row.get('duration_source')}")
        lines.append(f"- duration_conflict: {row.get('duration_conflict')}")
        lines.append(f"- reference_image: {row.get('reference_image_path')}")
        if row.get("image_prompt"):
            lines.append(f"- image_prompt: {row.get('image_prompt')}")
        if row.get("video_prompt"):
            lines.append(f"- video_prompt: {row.get('video_prompt')}")
        if row.get("audio_prompt"):
            lines.append(f"- audio_prompt: {row.get('audio_prompt')}")
        if row.get("tts_text"):
            lines.append(f"- tts_text: {row.get('tts_text')}")
        lines.append("")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def _write_lines_text(path: Path, rows: list[dict[str, Any]]) -> None:
    lines: list[str] = []
    for idx, row in enumerate(rows, start=1):
        text = str(row.get("video_prompt") or row.get("image_prompt") or "").strip()
        lines.append(f"{idx:02d}. [{row['shot_id']}] {text}")
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
