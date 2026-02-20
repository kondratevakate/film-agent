"""Backward-compatibility wrapper for legacy openai_video naming."""

from __future__ import annotations

from film_agent.providers.video_sora import build_sora_video_payload


def build_openai_video_payload(prompt: str, duration_s: int, resolution: str, fps: int, seed: int) -> dict:
    return build_sora_video_payload(prompt=prompt, duration_s=duration_s, resolution=resolution, fps=fps, seed=seed)
