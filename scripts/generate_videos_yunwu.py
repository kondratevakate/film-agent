#!/usr/bin/env python3
"""Direct video generation via Yunwu without OpenAI dependencies.

Usage:
    python scripts/generate_videos_yunwu.py --run-id the-trace-010 --iteration 3

This script:
1. Reads vimax_lines.json
2. Generates video for each shot via Yunwu API
3. Runs QC via Yunwu VLM (qwen3-vl-plus by default)
4. Saves videos to render_outputs directory
5. Creates a manifest with QC results
"""

from __future__ import annotations

import argparse
import base64
import json
import mimetypes
import os
import sys
import time
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from film_agent.providers.video_veo_yunwu import YunwuVeoClient, build_veo_yunwu_video_payload


def load_env():
    """Load .env file if exists."""
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                os.environ.setdefault(key.strip(), value.strip())


def image_to_base64_url(path: Path, max_size_kb: int = 1500) -> str:
    """Convert image to base64 data URL, compressing if needed."""
    try:
        from PIL import Image
    except ImportError:
        # Fallback without compression
        raw = path.read_bytes()
        b64 = base64.b64encode(raw).decode("utf-8")
        mime_type, _ = mimetypes.guess_type(path.name)
        mime = mime_type or "image/png"
        return f"data:{mime};base64,{b64}"

    # Load and potentially compress
    img = Image.open(path)

    # Convert to RGB if needed
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Try JPEG compression at various qualities
    for quality in [85, 70, 55, 40]:
        buffer = BytesIO()
        img.save(buffer, format="JPEG", quality=quality, optimize=True)
        data = buffer.getvalue()
        if len(data) <= max_size_kb * 1024:
            b64 = base64.b64encode(data).decode("utf-8")
            return f"data:image/jpeg;base64,{b64}"

    # If still too large, resize
    max_dim = 1024
    ratio = min(max_dim / img.width, max_dim / img.height)
    if ratio < 1:
        new_size = (int(img.width * ratio), int(img.height * ratio))
        img = img.resize(new_size, Image.LANCZOS)

    buffer = BytesIO()
    img.save(buffer, format="JPEG", quality=60, optimize=True)
    data = buffer.getvalue()
    b64 = base64.b64encode(data).decode("utf-8")
    return f"data:image/jpeg;base64,{b64}"


def run_qc_via_yunwu(
    *,
    api_key: str,
    model: str,
    frame_path: Path,
    reference_path: Path | None,
    video_prompt: str,
    shot_id: str,
) -> dict:
    """Run QC via Yunwu VLM API."""
    import requests

    base_url = "https://yunwu.ai"
    url = f"{base_url}/v1/chat/completions"
    headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Build message with images
    content = [
        {
            "type": "text",
            "text": (
                "You are a video quality control judge. Evaluate how well the generated frame matches the prompt.\n\n"
                f"Shot ID: {shot_id}\n"
                f"Video prompt: {video_prompt}\n\n"
                "Return JSON only with fields:\n"
                "- score: 0.0-1.0 (how well frame matches prompt)\n"
                "- reason_codes: array of short strings (e.g., 'good_composition', 'matches_prompt', 'wrong_lighting')\n"
                "- summary: one sentence explanation\n\n"
                "Scoring dimensions: prompt adherence, composition, artifact severity, visual quality."
            ),
        }
    ]

    if reference_path and reference_path.exists():
        content.append({"type": "text", "text": "Reference image:"})
        content.append({
            "type": "image_url",
            "image_url": {"url": image_to_base64_url(reference_path)},
        })

    content.append({"type": "text", "text": "Generated frame:"})
    content.append({
        "type": "image_url",
        "image_url": {"url": image_to_base64_url(frame_path)},
    })

    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": "You are a strict visual QC judge. Return valid JSON only."},
            {"role": "user", "content": content},
        ],
        "max_tokens": 500,
        "temperature": 0.1,
    }

    try:
        response = requests.post(url, headers=headers, json=payload, timeout=60)
        response.raise_for_status()
        body = response.json()
        text = body.get("choices", [{}])[0].get("message", {}).get("content", "")

        # Parse JSON from response
        import re
        json_match = re.search(r'\{[^{}]*\}', text, re.DOTALL)
        if json_match:
            result = json.loads(json_match.group())
            score = float(result.get("score", 0.5))
            return {
                "score": max(0.0, min(1.0, score)),
                "reason_codes": result.get("reason_codes", []),
                "summary": result.get("summary", ""),
                "qc_available": True,
            }
        return {
            "score": 0.5,
            "reason_codes": ["parse_error"],
            "summary": "Could not parse QC response",
            "qc_available": True,
        }
    except Exception as e:
        return {
            "score": None,
            "reason_codes": ["qc_error"],
            "summary": str(e),
            "qc_available": False,
        }


def extract_frame(video_path: Path, frame_path: Path) -> bool:
    """Extract middle frame from video."""
    try:
        from moviepy import VideoFileClip
    except ImportError:
        print("  Warning: moviepy not available, skipping frame extraction")
        return False

    try:
        clip = VideoFileClip(str(video_path))
        t = max(0.0, min(clip.duration / 2.0, clip.duration - 0.05))
        frame_path.parent.mkdir(parents=True, exist_ok=True)
        clip.save_frame(str(frame_path), t=t)
        clip.close()
        return frame_path.exists()
    except Exception as e:
        print(f"  Frame extraction error: {e}")
        return False


def build_compressed_payload(
    prompt: str,
    reference_image_path: Path | None,
    model: str,
    aspect_ratio: str,
) -> dict:
    """Build payload with compressed reference image."""
    payload = {
        "prompt": prompt,
        "model": model,
        "images": [],
        "enhance_prompt": True,
    }

    if reference_image_path and reference_image_path.exists():
        compressed_uri = image_to_base64_url(reference_image_path, max_size_kb=1500)
        payload["images"] = [compressed_uri]

    if model.startswith("veo3"):
        payload["aspect_ratio"] = aspect_ratio

    return payload


def main():
    parser = argparse.ArgumentParser(description="Generate videos via Yunwu API")
    parser.add_argument("--run-id", required=True, help="Run ID (e.g., the-trace-010)")
    parser.add_argument("--iteration", type=int, default=3, help="Iteration number")
    parser.add_argument("--model", default="veo3.1-fast", help="Yunwu video model")
    parser.add_argument("--qc-model", default="qwen3-vl-plus", help="Yunwu VLM for QC")
    parser.add_argument("--qc-threshold", type=float, default=0.6, help="QC pass threshold")
    parser.add_argument("--aspect-ratio", default="16:9", help="Aspect ratio")
    parser.add_argument("--poll-interval", type=float, default=5.0, help="Poll interval in seconds")
    parser.add_argument("--timeout", type=float, default=600.0, help="Timeout per shot in seconds")
    parser.add_argument("--dry-run", action="store_true", help="Don't actually call API")
    parser.add_argument("--skip-qc", action="store_true", help="Skip QC step")
    parser.add_argument("--no-reference", action="store_true", help="Don't use reference images")
    parser.add_argument("--shots", help="Comma-separated shot IDs to generate (default: all)")
    parser.add_argument("--skip-existing", action="store_true", help="Skip shots that already have video")
    args = parser.parse_args()

    load_env()
    yunwu_key = os.environ.get("YUNWU_API_KEY", "")
    if not yunwu_key and not args.dry_run:
        print("ERROR: YUNWU_API_KEY not set in environment or .env file")
        sys.exit(1)

    base_dir = Path(__file__).parent.parent
    iter_key = f"iter-{args.iteration:02d}"
    vimax_input_dir = base_dir / "runs" / args.run_id / "iterations" / iter_key / "vimax_input"
    lines_path = vimax_input_dir / "vimax_lines.json"

    if not lines_path.exists():
        print(f"ERROR: {lines_path} not found")
        sys.exit(1)

    lines_payload = json.loads(lines_path.read_text(encoding="utf-8"))
    lines = lines_payload.get("lines", [])
    if not lines:
        print("ERROR: No lines in vimax_lines.json")
        sys.exit(1)

    # Filter shots if specified
    selected_shots = None
    if args.shots:
        selected_shots = set(s.strip() for s in args.shots.split(","))

    # Output directory
    output_dir = base_dir / "runs" / args.run_id / "iterations" / iter_key / "render_outputs" / "yunwu_direct"
    output_dir.mkdir(parents=True, exist_ok=True)
    qc_frames_dir = output_dir / "qc_frames"
    qc_frames_dir.mkdir(parents=True, exist_ok=True)

    client = YunwuVeoClient(api_key=yunwu_key) if not args.dry_run else None

    # Load existing manifest if exists
    manifest_path = output_dir / "render_manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        existing_shots = {s["shot_id"]: s for s in manifest.get("shots", [])}
    else:
        manifest = {
            "run_id": args.run_id,
            "iteration": args.iteration,
            "model": args.model,
            "qc_model": args.qc_model,
            "qc_threshold": args.qc_threshold,
            "aspect_ratio": args.aspect_ratio,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "dry_run": args.dry_run,
            "shots": [],
        }
        existing_shots = {}

    total = len(lines)
    completed = 0
    failed = 0
    skipped = 0
    qc_passed = 0
    qc_failed = 0

    for idx, line in enumerate(lines, start=1):
        shot_id = str(line.get("shot_id", "")).strip()
        if not shot_id:
            continue

        if selected_shots and shot_id not in selected_shots:
            print(f"[{idx}/{total}] Skipping {shot_id} (not in selection)")
            continue

        output_path = output_dir / f"{idx:02d}_{shot_id}.mp4"

        # Check if already completed
        if args.skip_existing:
            existing = existing_shots.get(shot_id)
            if existing and existing.get("status") == "completed" and output_path.exists():
                print(f"[{idx}/{total}] Skipping {shot_id} (already completed)")
                skipped += 1
                continue

        video_prompt = str(line.get("video_prompt") or line.get("image_prompt") or "").strip()
        if not video_prompt:
            print(f"[{idx}/{total}] {shot_id}: No prompt, skipping")
            continue

        # Build prompt with negative constraints
        negative = str(line.get("negative_prompt", "")).strip()
        full_prompt = video_prompt
        if negative:
            full_prompt = f"{video_prompt}\nAvoid: {negative}"

        # Reference image
        ref_path = None
        if not args.no_reference:
            ref_path_raw = line.get("reference_image_path", "")
            if ref_path_raw:
                candidate = base_dir / ref_path_raw
                if candidate.exists():
                    ref_path = candidate
                else:
                    # Try absolute
                    abs_path = Path(ref_path_raw)
                    if abs_path.exists():
                        ref_path = abs_path

        frame_path = qc_frames_dir / f"{idx:02d}_{shot_id}.png"

        print(f"\n[{idx}/{total}] Generating {shot_id}...")
        print(f"  Prompt: {video_prompt[:80]}...")
        print(f"  Reference: {ref_path or 'none (prompt only)'}")
        print(f"  Output: {output_path}")

        shot_entry = {
            "shot_id": shot_id,
            "index": idx,
            "prompt": full_prompt[:200] + "..." if len(full_prompt) > 200 else full_prompt,
            "reference_image": str(ref_path) if ref_path else None,
            "output_path": str(output_path),
            "frame_path": str(frame_path),
            "status": "pending",
            "qc": None,
        }

        if args.dry_run:
            shot_entry["status"] = "dry_run"
            print(f"  [DRY RUN] Would generate video")
            # Update or add shot entry
            existing_shots[shot_id] = shot_entry
            continue

        try:
            # Build payload with compression
            payload = build_compressed_payload(
                prompt=full_prompt,
                reference_image_path=ref_path,
                model=args.model,
                aspect_ratio=args.aspect_ratio,
            )

            start_time = time.time()
            task_id = client.create_task(payload)
            print(f"  Task created: {task_id}")

            result = client.wait_for_completion(
                task_id,
                poll_interval_s=args.poll_interval,
                timeout_s=args.timeout,
            )
            print(f"  Task completed, downloading video...")

            client.download_video(result.video_url, output_path)
            elapsed = time.time() - start_time

            shot_entry["status"] = "completed"
            shot_entry["task_id"] = task_id
            shot_entry["video_url"] = result.video_url
            shot_entry["elapsed_s"] = round(elapsed, 1)
            completed += 1
            print(f"  Video SUCCESS in {elapsed:.1f}s")

            # Run QC if not skipped
            if not args.skip_qc:
                print(f"  Running QC...")
                if extract_frame(output_path, frame_path):
                    qc_result = run_qc_via_yunwu(
                        api_key=yunwu_key,
                        model=args.qc_model,
                        frame_path=frame_path,
                        reference_path=ref_path,
                        video_prompt=video_prompt,
                        shot_id=shot_id,
                    )
                    shot_entry["qc"] = qc_result

                    score = qc_result.get("score")
                    if score is not None and score >= args.qc_threshold:
                        qc_passed += 1
                        shot_entry["qc_decision"] = "pass"
                        print(f"  QC PASS: score={score:.2f}, {qc_result.get('summary', '')}")
                    else:
                        qc_failed += 1
                        shot_entry["qc_decision"] = "fail"
                        print(f"  QC FAIL: score={score}, {qc_result.get('summary', '')}")
                else:
                    shot_entry["qc"] = {"error": "frame_extraction_failed"}
                    shot_entry["qc_decision"] = "skip"

        except Exception as e:
            shot_entry["status"] = "failed"
            shot_entry["error"] = str(e)
            failed += 1
            print(f"  FAILED: {e}")

        # Update shot entry
        existing_shots[shot_id] = shot_entry

        # Rebuild manifest shots list in order
        manifest["shots"] = [existing_shots.get(str(l.get("shot_id"))) for l in lines if str(l.get("shot_id")) in existing_shots]
        manifest["shots"] = [s for s in manifest["shots"] if s is not None]

        # Save manifest after each shot
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")

    # Final summary
    print(f"\n{'='*60}")
    print(f"VIDEO: {completed} completed, {failed} failed, {skipped} skipped")
    if not args.skip_qc and completed > 0:
        print(f"QC: {qc_passed} passed, {qc_failed} failed (threshold={args.qc_threshold})")
    print(f"Output directory: {output_dir}")
    print(f"Manifest: {manifest_path}")

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
