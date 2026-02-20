"""Shared utilities for parsing OpenAI API responses."""

from __future__ import annotations

import json
from typing import Any


def extract_response_text(response: Any) -> str:
    """Extract text content from OpenAI Responses API response.

    Works with both the new Responses API (SDK 2.x) and older formats.
    """
    data = response.model_dump() if hasattr(response, "model_dump") else {}
    output = data.get("output", []) if isinstance(data, dict) else []
    chunks: list[str] = []
    for item in output:
        if not isinstance(item, dict):
            continue
        for content in item.get("content", []):
            if not isinstance(content, dict):
                continue
            text = content.get("text")
            if text:
                chunks.append(str(text))
    return "\n".join(chunks)


def extract_json_object(text: str) -> Any:
    """Extract JSON object from response text.

    Handles:
    - Plain JSON
    - JSON wrapped in markdown code blocks (```json ... ```)
    - JSON embedded in other text (finds first valid JSON object)

    Raises:
        ValueError: If no valid JSON object can be extracted.
    """
    cleaned = text.strip()

    # Remove markdown code block wrappers
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`")
        if cleaned.lower().startswith("json"):
            cleaned = cleaned[4:].strip()

    # Try direct parse first
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find first JSON object in text
    decoder = json.JSONDecoder()
    for idx, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(cleaned[idx:])
            return obj
        except json.JSONDecodeError:
            continue

    raise ValueError("Could not parse JSON object from response text.")
