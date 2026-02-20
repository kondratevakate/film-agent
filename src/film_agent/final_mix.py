"""Final video+audio mix assembly for ViMax pipeline outputs."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from film_agent.io.hashing import sha256_file
from film_agent.io.json_io import dump_canonical_json, load_json


@dataclass(frozen=True)
class FinalMixResult:
    output_video_path: Path
    manifest_path: Path
    total_duration_s: float
    shot_count: int


def build_shot_timeline(lines: list[dict[str, Any]]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    cursor = 0.0
    for row in lines:
        shot_id = str(row.get("shot_id", "")).strip()
        if not shot_id:
            raise ValueError("Timeline line is missing shot_id.")
        duration = float(row.get("duration_s", 0.0) or 0.0)
        if duration <= 0:
            raise ValueError(f"Timeline line {shot_id} has invalid duration_s: {duration}")
        entries.append({"shot_id": shot_id, "start_s": round(cursor, 4), "duration_s": duration})
        cursor += duration
    return entries


def build_final_mix(
    *,
    run_id: str,
    iteration: int,
    lines_path: Path,
    render_manifest_path: Path,
    render_qc_path: Path,
    output_dir: Path,
    openai_api_key: str,
    tts_model: str = "gpt-4o-mini-tts",
    tts_voice: str = "alloy",
    dry_run: bool = False,
) -> FinalMixResult:
    lines_payload = load_json(lines_path)
    lines = lines_payload.get("lines") if isinstance(lines_payload, dict) else None
    if not isinstance(lines, list) or not lines:
        raise ValueError("vimax_lines.json has no lines.")
    global_music_prompt = str(lines_payload.get("music_prompt", "") if isinstance(lines_payload, dict) else "").strip()

    render_manifest = load_json(render_manifest_path)
    render_shots = render_manifest.get("shots") if isinstance(render_manifest, dict) else None
    if not isinstance(render_shots, list) or not render_shots:
        raise ValueError("render_manifest.json has no shots.")

    qc_payload = load_json(render_qc_path)
    qc_rows = qc_payload.get("shots") if isinstance(qc_payload, dict) else None
    if not isinstance(qc_rows, list) or not qc_rows:
        raise ValueError("render_qc.json has no shots.")

    qc_map = {str(item.get("shot_id")): item for item in qc_rows if isinstance(item, dict)}
    failed_shots = [shot_id for shot_id, item in qc_map.items() if str(item.get("decision")) == "fail"]
    if failed_shots:
        raise ValueError(f"Cannot build final mix: failed shots present {sorted(failed_shots)}")

    render_map: dict[str, dict[str, Any]] = {}
    for row in render_shots:
        if not isinstance(row, dict):
            continue
        shot_id = str(row.get("shot_id", "")).strip()
        if not shot_id:
            continue
        render_map[shot_id] = row

    timeline = build_shot_timeline(lines)
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir = output_dir / "audio_segments"
    audio_dir.mkdir(parents=True, exist_ok=True)

    shot_manifest: list[dict[str, Any]] = []
    failed_missing_video: list[str] = []
    for entry in timeline:
        shot_id = entry["shot_id"]
        render_row = render_map.get(shot_id)
        output_path = Path(str(render_row.get("output_path", ""))) if render_row else Path()
        status = str(render_row.get("status", "")) if render_row else ""
        if status != "completed" or not output_path.exists():
            failed_missing_video.append(shot_id)
            continue
        shot_manifest.append(
            {
                **entry,
                "video_file": str(output_path),
                "video_sha256": sha256_file(output_path),
            }
        )

    if failed_missing_video:
        raise ValueError(f"Cannot build final mix: missing completed video files for {sorted(failed_missing_video)}")

    audio_segments: list[dict[str, Any]] = []
    for idx, row in enumerate(lines, start=1):
        shot_id = str(row.get("shot_id"))
        start_s = next((item["start_s"] for item in timeline if item["shot_id"] == shot_id), 0.0)
        duration = float(row.get("duration_s", 0.0) or 0.0)

        tts_text = str(row.get("tts_text") or "").strip()
        if tts_text:
            segment_path = audio_dir / f"{idx:02d}_{shot_id}_tts.mp3"
            if not dry_run:
                _generate_tts_mp3(
                    api_key=openai_api_key,
                    text=tts_text,
                    out_path=segment_path,
                    model=tts_model,
                    voice=tts_voice,
                )
            audio_segments.append(
                {
                    "shot_id": shot_id,
                    "kind": "tts",
                    "start_s": start_s,
                    "duration_hint_s": duration,
                    "path": str(segment_path),
                    "status": "generated" if not dry_run else "planned",
                    "text": tts_text,
                }
            )

        shot_audio_prompt = str(row.get("audio_prompt") or "").strip()
        if shot_audio_prompt:
            segment_path = audio_dir / f"{idx:02d}_{shot_id}_audio_prompt.mp3"
            if not dry_run:
                _generate_tts_mp3(
                    api_key=openai_api_key,
                    text=shot_audio_prompt,
                    out_path=segment_path,
                    model=tts_model,
                    voice=tts_voice,
                )
            audio_segments.append(
                {
                    "shot_id": shot_id,
                    "kind": "audio_prompt_tts",
                    "start_s": start_s,
                    "duration_hint_s": duration,
                    "path": str(segment_path),
                    "status": "generated" if not dry_run else "planned",
                    "text": shot_audio_prompt,
                }
            )

    total_duration = sum(float(item["duration_s"]) for item in shot_manifest)

    if global_music_prompt:
        global_music_path = audio_dir / "00_global_music_prompt.mp3"
        if not dry_run:
            _generate_tts_mp3(
                api_key=openai_api_key,
                text=global_music_prompt,
                out_path=global_music_path,
                model=tts_model,
                voice=tts_voice,
            )
        audio_segments.append(
            {
                "shot_id": "__global__",
                "kind": "music_prompt_tts",
                "start_s": 0.0,
                "duration_hint_s": total_duration,
                "path": str(global_music_path),
                "status": "generated" if not dry_run else "planned",
                "text": global_music_prompt,
            }
        )

    final_video_path = output_dir / "final_video_with_audio.mp4"
    if not dry_run:
        _compose_video_with_audio(
            shot_manifest=shot_manifest,
            audio_segments=audio_segments,
            output_path=final_video_path,
        )

    final_manifest = {
        "run_id": run_id,
        "iteration": iteration,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "output_video": str(final_video_path),
        "output_video_sha256": sha256_file(final_video_path) if final_video_path.exists() else None,
        "total_duration_s": total_duration,
        "shot_count": len(shot_manifest),
        "shots": shot_manifest,
        "audio_segments": audio_segments,
    }
    manifest_path = output_dir / "final_mix_manifest.json"
    dump_canonical_json(manifest_path, final_manifest)

    return FinalMixResult(
        output_video_path=final_video_path,
        manifest_path=manifest_path,
        total_duration_s=total_duration,
        shot_count=len(shot_manifest),
    )


def _generate_tts_mp3(*, api_key: str, text: str, out_path: Path, model: str, voice: str) -> None:
    if not api_key.strip():
        raise ValueError("OpenAI API key is required for TTS generation.")
    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - runtime dependency issue
        raise RuntimeError("openai package is required for TTS generation.") from exc

    client = OpenAI(api_key=api_key)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    response = client.audio.speech.create(
        model=model,
        voice=voice,
        input=text,
        format="mp3",
    )

    if hasattr(response, "stream_to_file"):
        response.stream_to_file(str(out_path))
        return
    if hasattr(response, "read"):
        out_path.write_bytes(response.read())
        return
    content = getattr(response, "content", None)
    if isinstance(content, (bytes, bytearray)):
        out_path.write_bytes(bytes(content))
        return
    raise RuntimeError("Unexpected TTS response format; cannot persist audio.")


def _compose_video_with_audio(*, shot_manifest: list[dict[str, Any]], audio_segments: list[dict[str, Any]], output_path: Path) -> None:
    try:
        from moviepy import AudioFileClip, CompositeAudioClip, VideoFileClip, concatenate_videoclips
    except Exception as exc:  # pragma: no cover - runtime dependency issue
        raise RuntimeError("moviepy is required for final video+audio mixing. Install: pip install moviepy") from exc

    video_clips = [VideoFileClip(str(item["video_file"])) for item in shot_manifest]
    video = concatenate_videoclips(video_clips)

    speech_clips = []
    for seg in audio_segments:
        if seg.get("kind") not in {"tts", "audio_prompt_tts", "music_prompt_tts"}:
            continue
        path = Path(str(seg.get("path")))
        if not path.exists():
            continue
        clip = AudioFileClip(str(path)).with_start(float(seg.get("start_s", 0.0)))
        if seg.get("kind") in {"audio_prompt_tts", "music_prompt_tts"} and hasattr(clip, "with_volume_scaled"):
            clip = clip.with_volume_scaled(0.35)
        speech_clips.append(clip)

    if speech_clips:
        audio = CompositeAudioClip(speech_clips)
        video = video.with_audio(audio)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    video.write_videofile(str(output_path), codec="libx264", audio_codec="aac")

    for clip in speech_clips:
        clip.close()
    for clip in video_clips:
        clip.close()
    video.close()
