"""OpenAI video payload helper."""

from __future__ import annotations


def build_openai_video_payload(prompt: str, duration_s: int, resolution: str, fps: int, seed: int) -> dict:
    return {
        "prompt": prompt,
        "duration_s": duration_s,
        "resolution": resolution,
        "fps": fps,
        "seed": seed,
    }
