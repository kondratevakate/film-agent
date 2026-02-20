"""OpenAI image payload helper."""

from __future__ import annotations


def build_openai_image_payload(prompt: str, size: str = "1024x1024") -> dict:
    return {
        "prompt": prompt,
        "size": size,
    }
