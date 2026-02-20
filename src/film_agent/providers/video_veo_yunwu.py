"""Veo (Yunwu API) payload builder and minimal HTTP client."""

from __future__ import annotations

import base64
import mimetypes
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


class YunwuVeoError(RuntimeError):
    """Raised when Yunwu Veo API returns an unusable response."""


def _require_requests():
    try:
        import requests
    except ImportError as exc:  # pragma: no cover - exercised only without optional deps
        raise RuntimeError("requests package is required. Install with: pip install -e .[providers]") from exc
    return requests


def image_path_to_data_uri(image_path: str | Path) -> str:
    path = Path(image_path)
    raw = path.read_bytes()
    b64 = base64.b64encode(raw).decode("utf-8")
    mime_type, _ = mimetypes.guess_type(path.name)
    mime = mime_type or "application/octet-stream"
    return f"data:{mime};base64,{b64}"


def build_veo_yunwu_video_payload(
    prompt: str,
    reference_image_paths: Iterable[str | Path] = (),
    *,
    model: str = "veo3.1-fast",
    aspect_ratio: str = "16:9",
    enhance_prompt: bool = True,
) -> dict[str, Any]:
    """Build Yunwu /v1/video/create payload.

    Reuses the same conventions as ViMax:
    - `images` is a list of data URI strings.
    - `aspect_ratio` is applied for Veo3 family only.
    """

    payload: dict[str, Any] = {
        "prompt": prompt,
        "model": model,
        "images": [image_path_to_data_uri(item) for item in reference_image_paths],
        "enhance_prompt": enhance_prompt,
    }
    if model.startswith("veo3"):
        payload["aspect_ratio"] = aspect_ratio
    return payload


@dataclass(frozen=True)
class YunwuVeoTaskResult:
    task_id: str
    status: str
    payload: dict[str, Any]
    video_url: str


class YunwuVeoClient:
    """Small polling client for Yunwu Veo async tasks."""

    def __init__(self, api_key: str, *, base_url: str = "https://yunwu.ai", request_timeout_s: float = 60.0):
        if not api_key.strip():
            raise ValueError("api_key must be provided.")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.request_timeout_s = request_timeout_s

    def create_task(self, payload: dict[str, Any]) -> str:
        requests = _require_requests()
        url = f"{self.base_url}/v1/video/create"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        response = requests.post(url, headers=headers, json=payload, timeout=self.request_timeout_s)
        response.raise_for_status()
        body = response.json()
        task_id = body.get("id")
        if not task_id:
            raise YunwuVeoError(f"Task id missing in create response: {body}")
        return str(task_id)

    def query_task(self, task_id: str) -> dict[str, Any]:
        requests = _require_requests()
        url = f"{self.base_url}/v1/video/query"
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }
        response = requests.get(
            url,
            params={"id": task_id},
            headers=headers,
            timeout=self.request_timeout_s,
        )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise YunwuVeoError("Query response is not a JSON object.")
        return payload

    def wait_for_completion(self, task_id: str, *, poll_interval_s: float = 2.0, timeout_s: float = 900.0) -> YunwuVeoTaskResult:
        deadline = time.time() + timeout_s
        while True:
            payload = self.query_task(task_id)
            status = str(payload.get("status", "")).strip().lower()
            if status == "completed":
                video_url = payload.get("video_url")
                if not video_url:
                    raise YunwuVeoError(f"Task completed but video_url missing: {payload}")
                return YunwuVeoTaskResult(
                    task_id=task_id,
                    status=status,
                    payload=payload,
                    video_url=str(video_url),
                )
            if status == "failed":
                raise YunwuVeoError(f"Task {task_id} failed: {payload}")
            if time.time() >= deadline:
                raise TimeoutError(f"Timed out waiting for Yunwu Veo task {task_id}.")
            time.sleep(max(0.1, poll_interval_s))

    def download_video(self, video_url: str, target_path: str | Path) -> Path:
        requests = _require_requests()
        path = Path(target_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        response = requests.get(video_url, stream=True, timeout=self.request_timeout_s)
        response.raise_for_status()
        with path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    handle.write(chunk)
        return path
