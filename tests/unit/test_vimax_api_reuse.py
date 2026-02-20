from __future__ import annotations

from pathlib import Path

from film_agent.providers.video_veo_yunwu import build_veo_yunwu_video_payload, image_path_to_data_uri
from film_agent.render_api import build_video_prompt_text, resolution_to_aspect_ratio


def test_image_path_to_data_uri_uses_mime_prefix(tmp_path: Path) -> None:
    image = tmp_path / "frame.png"
    image.write_bytes(b"fake-png-bytes")

    value = image_path_to_data_uri(image)

    assert value.startswith("data:image/png;base64,")


def test_build_veo_payload_includes_aspect_ratio_for_veo3(tmp_path: Path) -> None:
    image = tmp_path / "ref.jpg"
    image.write_bytes(b"fake-jpg-bytes")

    payload = build_veo_yunwu_video_payload(
        prompt="shot prompt",
        reference_image_paths=[image],
        model="veo3.1-fast",
        aspect_ratio="21:9",
    )

    assert payload["model"] == "veo3.1-fast"
    assert payload["aspect_ratio"] == "21:9"
    assert len(payload["images"]) == 1


def test_build_veo_payload_skips_aspect_ratio_for_veo2() -> None:
    payload = build_veo_yunwu_video_payload(
        prompt="shot prompt",
        model="veo2-fast-frames",
        aspect_ratio="21:9",
    )

    assert payload["model"] == "veo2-fast-frames"
    assert "aspect_ratio" not in payload


def test_resolution_to_aspect_ratio() -> None:
    assert resolution_to_aspect_ratio("1920x1080") == "16:9"
    assert resolution_to_aspect_ratio("1080x1920") == "9:16"
    assert resolution_to_aspect_ratio("bad-value") == "16:9"


def test_build_video_prompt_text_appends_negatives() -> None:
    prompt = build_video_prompt_text(
        "Camera pushes in to close-up.",
        ["identity drift", " extra limbs ", ""],
    )
    assert "Avoid: identity drift; extra limbs" in prompt
