"""ElevenLabs payload helper."""

from __future__ import annotations


def build_elevenlabs_tts_payload(text: str, voice_id: str, model_id: str = "eleven_multilingual_v2") -> dict:
    return {
        "text": text,
        "model_id": model_id,
        "voice_settings": {
            "stability": 0.4,
            "similarity_boost": 0.75,
        },
        "voice_id": voice_id,
    }
