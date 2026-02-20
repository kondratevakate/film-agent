"""NanoBanana payload helper."""

from __future__ import annotations


def build_nanobanana_payload(prompt: str, style_reference: str | None = None) -> dict:
    payload = {
        "prompt": prompt,
    }
    if style_reference:
        payload["style_reference"] = style_reference
    return payload
