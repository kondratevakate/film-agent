"""
HiggsFieldClient - API wrapper for Higgsfield video and image generation.

Uses the official higgsfield-client SDK with backward-compatible API.
"""

import os
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# Convert legacy HIGS_* env vars to HF_* before importing SDK
if not os.getenv("HF_KEY") and not os.getenv("HF_API_KEY"):
    if os.getenv("HIGS_API_KEY") and os.getenv("HIGS_API_SECRET"):
        os.environ["HF_API_KEY"] = os.getenv("HIGS_API_KEY", "")
        os.environ["HF_API_SECRET"] = os.getenv("HIGS_API_SECRET", "")

import higgsfield_client as hf

logger = logging.getLogger(__name__)

# Common motion presets with their UUIDs
MOTION_PRESETS = {
    "static": "fa3ddb7c-53ee-4383-aa17-97ae65f180e5",
    "dolly_in": "81ca2cd2-05db-4222-9ba0-a32e5185adfb",
    "dolly_out": "12ac8798-5370-4801-91a6-f1acb425fc4a",
    "dolly_left": "71f0f8bc-0e5d-4d32-b34f-bd74a5e3cba8",
    "dolly_right": "15ddc007-4723-42c1-8446-2af69af4879f",
    "dolly_zoom_in": "f0ca4e62-f65d-4a6d-83c1-ecbaa4d492ba",
    "dolly_zoom_out": "2df82f5f-064a-4a7e-8b59-24ac446cb1df",
    "super_dolly_in": "3a24a20d-b494-4e8a-9b5f-4ef05ee5073d",
    "super_dolly_out": "679c128d-a109-4267-8007-12f653f6346d",
    "crane_up": "68af9add-43ea-4261-a706-16b640fdcff9",
    "crane_down": "b26dcbe5-e784-4893-b8a3-2bd4f848e90a",
    "crane_over_head": "0d736605-3a09-4a39-bcfe-b556fba7dd22",
    "zoom_in": "fbcbec5b-30f8-4b17-ba6e-8e8d5b265562",
    "zoom_out": "263600e4-45c0-4c13-9579-40a9278af37c",
    "crash_zoom_in": "3ec247ed-063d-476d-8266-48829c2eced6",
    "crash_zoom_out": "3f7a86be-c78f-4c5d-8dbf-7395a3fbeea1",
    "tilt_up": "2c9af101-fe7a-4299-91f3-e44431a0576f",
    "tilt_down": "ff67b0eb-a621-45a0-b92d-ce2549250149",
    "arc_left": "c5881721-05b1-47d9-94d6-0203863114e1",
    "arc_right": "a85cb3f2-f2be-4ee2-b3b9-808fc6a81acc",
    "orbit_360": "ea035f68-b350-40f1-b7f4-7dff999fdd67",
    "handheld": "5be9d262-82d7-4a74-babf-ee8fefd5c3c3",
    "whip_pan": "25c72c28-7857-4aa0-af92-ba5380f0e67d",
    "double_dolly": "bd133fba-ed35-433b-9cb2-87b1f5bb1139",
}

# Model paths for the official SDK
MODELS = {
    "image": "higgsfield-ai/soul/standard",
    "video_lite": "higgsfield-ai/dop/lite",
    "video_turbo": "higgsfield-ai/dop/turbo",
    "video_standard": "higgsfield-ai/dop/standard",
}


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
    Client for Higgsfield AI platform using official SDK.

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
            first_frame_url=result.output_url,
        )
    """

    @classmethod
    def from_env(cls) -> "HiggsFieldClient":
        """
        Load credentials from environment variables.

        Supports both official SDK vars (HF_API_KEY/HF_API_SECRET or HF_KEY)
        and legacy vars (HIGS_API_KEY/HIGS_API_SECRET) for backward compatibility.
        """
        # Check for official SDK environment variables
        if os.getenv("HF_KEY") or (os.getenv("HF_API_KEY") and os.getenv("HF_API_SECRET")):
            return cls()

        # Fallback to legacy environment variables
        api_key = os.getenv("HIGS_API_KEY", "")
        api_secret = os.getenv("HIGS_API_SECRET", "")

        if api_key and api_secret:
            # Set official SDK env vars from legacy vars
            os.environ["HF_API_KEY"] = api_key
            os.environ["HF_API_SECRET"] = api_secret
            logger.info("Using legacy HIGS_* environment variables")
            return cls()

        raise ValueError(
            "Higgsfield credentials not found. Set HF_KEY or HF_API_KEY/HF_API_SECRET "
            "(or legacy HIGS_API_KEY/HIGS_API_SECRET)"
        )

    def get_motion_id(self, motion_name: str) -> Optional[str]:
        """
        Get motion UUID by name.

        Args:
            motion_name: Motion name like "dolly_in", "crane_up", "static"

        Returns:
            Motion UUID or None if not found
        """
        return MOTION_PRESETS.get(motion_name.lower().replace(" ", "_"))

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
            resolution: Output resolution (1080p, 720p, 2K)
            negative_prompt: What to avoid in generation
            reference_image: URL or path of reference image

        Returns:
            GenerationResult with output URL
        """
        arguments = {
            "prompt": prompt,
            "aspect_ratio": aspect_ratio,
            "resolution": resolution,
        }

        if negative_prompt:
            arguments["negative_prompt"] = negative_prompt

        if reference_image:
            # Upload if it's a local path
            if Path(reference_image).exists():
                reference_image = self.upload_file(reference_image)
            arguments["reference_image"] = reference_image

        logger.info(f"Generating image: {prompt[:50]}...")

        try:
            result = hf.subscribe(MODELS["image"], arguments=arguments)

            # Extract output URL from result
            output_url = None
            if isinstance(result, dict):
                output_url = (
                    result.get("images", [{}])[0].get("url")
                    or result.get("output_url")
                    or result.get("url")
                )

            generation_id = result.get("id", "") if isinstance(result, dict) else ""

            logger.info(f"Image generation completed: {generation_id}")
            return GenerationResult(
                generation_id=generation_id,
                status="completed",
                output_url=output_url,
                metadata=result if isinstance(result, dict) else {"result": result},
            )

        except Exception as e:
            logger.error(f"Image generation failed: {e}")
            return GenerationResult(
                generation_id="",
                status="failed",
                error_message=str(e),
            )

    def generate_video(
        self,
        prompt: str,
        first_frame_url: Optional[str] = None,
        last_frame_url: Optional[str] = None,
        motion_names: Optional[list[str]] = None,
        motion_strength: float = 0.5,
        quality: str = "lite",
        enhance_prompt: bool = True,
    ) -> GenerationResult:
        """
        Generate a video using HiggsField DoP (Director of Photography).

        Args:
            prompt: Description of video action and motion
            first_frame_url: URL of the first frame image (publicly accessible HTTPS)
            last_frame_url: Optional URL of the last frame for interpolation
            motion_names: List of motion preset names, e.g. ["dolly_in", "crane_up"]
            motion_strength: Strength of motion effect (0.0 to 1.0)
            quality: "lite", "turbo", or "standard"
            enhance_prompt: Whether to use AI prompt enhancement

        Returns:
            GenerationResult with output video URL
        """
        # Convert motion names to API format
        motions = []
        if motion_names:
            for name in motion_names:
                motion_id = self.get_motion_id(name)
                if motion_id:
                    motions.append({"id": motion_id, "strength": motion_strength})

        arguments = {
            "prompt": prompt,
            "enhance_prompt": enhance_prompt,
            "motions": motions,
        }

        if first_frame_url:
            # Upload if it's a local path
            if Path(first_frame_url).exists():
                first_frame_url = self.upload_file(first_frame_url)
            arguments["image_url"] = first_frame_url

        if last_frame_url:
            if Path(last_frame_url).exists():
                last_frame_url = self.upload_file(last_frame_url)
            arguments["last_frame_url"] = last_frame_url

        logger.info(f"Generating video: {prompt[:50]}...")

        # Select model based on quality
        model_key = f"video_{quality}" if quality in ["lite", "turbo", "standard"] else "video_lite"
        model = MODELS.get(model_key, MODELS["video_lite"])

        try:
            result = hf.subscribe(model, arguments=arguments)

            # Extract output URL from result
            output_url = None
            if isinstance(result, dict):
                output_url = (
                    result.get("video", {}).get("url")
                    or result.get("output_url")
                    or result.get("url")
                )

            generation_id = result.get("id", "") if isinstance(result, dict) else ""

            logger.info(f"Video generation completed: {generation_id}")
            return GenerationResult(
                generation_id=generation_id,
                status="completed",
                output_url=output_url,
                metadata=result if isinstance(result, dict) else {"result": result},
            )

        except Exception as e:
            logger.error(f"Video generation failed: {e}")
            return GenerationResult(
                generation_id="",
                status="failed",
                error_message=str(e),
            )

    def upload_file(self, path: str | Path) -> str:
        """
        Upload a local file and return the URL.

        Uses the official SDK's upload functionality.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        logger.info(f"Uploading: {path}")
        return hf.upload_file(str(path))

    def download_result(self, url: str, output_path: str | Path) -> Path:
        """Download generated file from URL."""
        import requests

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
        try:
            status = hf.status(generation_id)

            if isinstance(status, hf.Completed):
                result = hf.result(generation_id)
                output_url = None
                if isinstance(result, dict):
                    output_url = (
                        result.get("video", {}).get("url")
                        or result.get("images", [{}])[0].get("url")
                        or result.get("output_url")
                    )
                return GenerationResult(
                    generation_id=generation_id,
                    status="completed",
                    output_url=output_url,
                    metadata=result if isinstance(result, dict) else {},
                )
            elif isinstance(status, hf.Failed):
                return GenerationResult(
                    generation_id=generation_id,
                    status="failed",
                    error_message=str(status),
                )
            elif isinstance(status, hf.NSFW):
                return GenerationResult(
                    generation_id=generation_id,
                    status="failed",
                    error_message="Content policy violation (NSFW)",
                )
            elif isinstance(status, hf.Cancelled):
                return GenerationResult(
                    generation_id=generation_id,
                    status="cancelled",
                )
            else:
                # Queued or InProgress
                return GenerationResult(
                    generation_id=generation_id,
                    status="in_progress",
                )

        except Exception as e:
            logger.error(f"Status check failed: {e}")
            return GenerationResult(
                generation_id=generation_id,
                status="unknown",
                error_message=str(e),
            )

    # Legacy compatibility method
    def load_image_as_base64(self, path: str | Path) -> str:
        """Load local image file as base64 string (legacy method)."""
        import base64

        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Image not found: {path}")

        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("utf-8")
