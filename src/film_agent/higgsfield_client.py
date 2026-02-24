"""
HiggsFieldClient - API wrapper for Higgsfield video and image generation.

Handles authentication, request formatting, and polling for results.
"""

import os
import time
import base64
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
import requests

logger = logging.getLogger(__name__)


class HiggsFieldError(Exception):
    """Error from Higgsfield API."""

    pass


@dataclass
class GenerationResult:
    """Result of a generation request."""

    generation_id: str
    status: str
    output_url: Optional[str] = None
    error_message: Optional[str] = None
    metadata: dict = field(default_factory=dict)


@dataclass
class HiggsFieldClient:
    """
    Client for Higgsfield AI platform.

    Supports both image and video generation with reference anchors.

    Example:
        client = HiggsFieldClient.from_env()

        # Generate image
        result = client.generate_image(
            prompt="Young woman in dark hakama, photorealistic",
            aspect_ratio="16:9"
        )

        # Generate video from image
        video_result = client.generate_video(
            prompt="She walks forward slowly",
            input_image=result.output_url,
            duration=5
        )
    """

    api_key: str = ""
    api_secret: str = ""
    base_url: str = "https://platform.higgsfield.ai"
    timeout: int = 30
    poll_interval: int = 5
    max_poll_attempts: int = 120  # 10 minutes max

    @classmethod
    def from_env(cls) -> "HiggsFieldClient":
        """Load credentials from environment variables."""
        api_key = os.getenv("HIGS_API_KEY", "")
        api_secret = os.getenv("HIGS_API_SECRET", "")

        if not api_key or not api_secret:
            raise ValueError(
                "HIGS_API_KEY and HIGS_API_SECRET must be set in environment"
            )

        return cls(api_key=api_key, api_secret=api_secret)

    def _get_headers(self) -> dict:
        """Get authentication headers."""
        return {
            "Authorization": f"Key {self.api_key}:{self.api_secret}",
            "Content-Type": "application/json",
        }

    def _make_request(
        self, method: str, endpoint: str, json_data: Optional[dict] = None
    ) -> dict:
        """Make authenticated request to API."""
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        try:
            if method == "GET":
                response = requests.get(url, headers=headers, timeout=self.timeout)
            elif method == "POST":
                response = requests.post(
                    url, headers=headers, json=json_data, timeout=self.timeout
                )
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            raise HiggsFieldError(f"API request failed: {e}") from e

    def generate_image(
        self,
        prompt: str,
        aspect_ratio: str = "16:9",
        resolution: str = "1080p",
        negative_prompt: Optional[str] = None,
        reference_image: Optional[str] = None,
    ) -> GenerationResult:
        """
        Generate an image using Higgsfield Soul model.

        Args:
            prompt: Text description of desired image
            aspect_ratio: Image aspect ratio (16:9, 1:1, 9:16)
            resolution: Output resolution (1080p, 720p)
            negative_prompt: What to avoid in generation
            reference_image: URL or base64 of reference image

        Returns:
            GenerationResult with output URL
        """
        payload = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }

        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        if reference_image:
            payload["reference_image"] = reference_image

        logger.info(f"Generating image: {prompt[:50]}...")

        response = self._make_request(
            "POST", "/higgsfield-ai/soul/standard", payload
        )

        # Get status URL and poll for result
        status_url = response.get("status_url", "")
        generation_id = response.get("id", "")

        if status_url:
            return self._poll_for_result(status_url, generation_id)

        return GenerationResult(
            generation_id=generation_id,
            status="submitted",
            metadata=response,
        )

    def generate_video(
        self,
        prompt: str,
        input_image: Optional[str] = None,
        duration: int = 5,
        fps: int = 24,
        motion_intensity: str = "medium",
        camera_motion: Optional[str] = None,
        negative_prompt: Optional[str] = None,
    ) -> GenerationResult:
        """
        Generate a video from prompt and optional input image.

        Args:
            prompt: Description of video action and motion
            input_image: URL or base64 of starting frame
            duration: Video duration in seconds
            fps: Frames per second
            motion_intensity: low, medium, high
            camera_motion: Camera movement description
            negative_prompt: What to avoid

        Returns:
            GenerationResult with output video URL
        """
        payload = {
            "prompt": prompt,
            "duration": duration,
            "fps": fps,
            "motion_intensity": motion_intensity,
        }

        if input_image:
            payload["input_image"] = input_image

        if camera_motion:
            payload["camera_motion"] = camera_motion

        if negative_prompt:
            payload["negative_prompt"] = negative_prompt

        logger.info(f"Generating video: {prompt[:50]}...")

        # Use video generation endpoint
        response = self._make_request(
            "POST", "/higgsfield-ai/video/standard", payload
        )

        status_url = response.get("status_url", "")
        generation_id = response.get("id", "")

        if status_url:
            return self._poll_for_result(status_url, generation_id)

        return GenerationResult(
            generation_id=generation_id,
            status="submitted",
            metadata=response,
        )

    def _poll_for_result(
        self, status_url: str, generation_id: str
    ) -> GenerationResult:
        """Poll status URL until generation completes."""
        attempts = 0

        while attempts < self.max_poll_attempts:
            try:
                response = requests.get(
                    status_url,
                    headers=self._get_headers(),
                    timeout=self.timeout,
                )
                response.raise_for_status()
                data = response.json()

                status = data.get("status", "").lower()

                if status == "completed":
                    output_url = data.get("output_url") or data.get("result", {}).get("url")
                    logger.info(f"Generation completed: {generation_id}")
                    return GenerationResult(
                        generation_id=generation_id,
                        status="completed",
                        output_url=output_url,
                        metadata=data,
                    )

                if status in ("failed", "error"):
                    error = data.get("error", "Unknown error")
                    logger.error(f"Generation failed: {error}")
                    return GenerationResult(
                        generation_id=generation_id,
                        status="failed",
                        error_message=error,
                        metadata=data,
                    )

                logger.debug(f"Generation status: {status}")
                time.sleep(self.poll_interval)
                attempts += 1

            except requests.exceptions.RequestException as e:
                logger.warning(f"Poll request failed: {e}")
                time.sleep(self.poll_interval)
                attempts += 1

        return GenerationResult(
            generation_id=generation_id,
            status="timeout",
            error_message=f"Polling timed out after {attempts} attempts",
        )

    def load_image_as_base64(self, path: str | Path) -> str:
        """Load local image file as base64 string."""
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")

        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")

    def download_result(self, url: str, output_path: str | Path) -> Path:
        """Download generated file from URL."""
        output_path = Path(output_path)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        response = requests.get(url, timeout=60)
        response.raise_for_status()

        with open(output_path, "wb") as f:
            f.write(response.content)

        logger.info(f"Downloaded to: {output_path}")
        return output_path

    def check_status(self, generation_id: str) -> GenerationResult:
        """Check status of a generation by ID."""
        response = self._make_request(
            "GET", f"/v1/generations/{generation_id}"
        )

        return GenerationResult(
            generation_id=generation_id,
            status=response.get("status", "unknown"),
            output_url=response.get("output_url"),
            metadata=response,
        )
