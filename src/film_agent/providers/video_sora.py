"""Sora payload helper."""

from __future__ import annotations


def build_sora_video_payload(prompt: str, duration_s: int, resolution: str, fps: int, seed: int) -> dict:
    return {
        "model": "sora-2",
        "prompt": prompt,
        "seconds": duration_s,
        "resolution": resolution,
        "fps": fps,
        "seed": seed,
    }
