"""
Image Uploader - Upload local images to hosting services for public URLs.

Supports:
- imgbb: Free image hosting with API (https://api.imgbb.com/)
"""

import base64
import logging
import os
from pathlib import Path
from typing import Optional
import requests

logger = logging.getLogger(__name__)


class ImageUploadError(Exception):
    """Error uploading image."""
    pass


def upload_to_imgbb(
    image_path: Path,
    api_key: Optional[str] = None,
    expiration: Optional[int] = None,
) -> str:
    """
    Upload image to imgbb and return public URL.

    Args:
        image_path: Path to local image file
        api_key: imgbb API key (or set IMGBB_API_KEY env var)
        expiration: Optional expiration time in seconds (60-15552000)

    Returns:
        Public URL of uploaded image

    Raises:
        ImageUploadError: If upload fails
    """
    api_key = api_key or os.getenv("IMGBB_API_KEY")
    if not api_key:
        raise ValueError("IMGBB_API_KEY not set. Get one from https://api.imgbb.com/")

    image_path = Path(image_path)
    if not image_path.exists():
        raise FileNotFoundError(f"Image not found: {image_path}")

    # Read and encode image
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode("utf-8")

    # Build request
    url = "https://api.imgbb.com/1/upload"
    payload = {
        "key": api_key,
        "image": image_data,
        "name": image_path.stem,
    }

    if expiration:
        payload["expiration"] = expiration

    try:
        response = requests.post(url, data=payload, timeout=60)
        response.raise_for_status()
        data = response.json()

        if not data.get("success"):
            error = data.get("error", {}).get("message", "Unknown error")
            raise ImageUploadError(f"imgbb upload failed: {error}")

        image_url = data["data"]["url"]
        logger.info(f"Uploaded {image_path.name} -> {image_url}")
        return image_url

    except requests.exceptions.RequestException as e:
        raise ImageUploadError(f"imgbb upload failed: {e}") from e


def upload_anchors_batch(
    anchors_dir: Path,
    api_key: Optional[str] = None,
    pattern: str = "*.png",
) -> dict[str, str]:
    """
    Upload all anchor images from a directory.

    Args:
        anchors_dir: Directory containing anchor images
        api_key: imgbb API key
        pattern: Glob pattern for images

    Returns:
        Dict mapping filename to public URL
    """
    anchors_dir = Path(anchors_dir)
    if not anchors_dir.exists():
        raise FileNotFoundError(f"Anchors directory not found: {anchors_dir}")

    urls = {}
    for image_path in anchors_dir.glob(pattern):
        try:
            url = upload_to_imgbb(image_path, api_key=api_key)
            urls[image_path.name] = url
        except Exception as e:
            logger.error(f"Failed to upload {image_path.name}: {e}")

    return urls


class AnchorCache:
    """
    Cache for uploaded anchor URLs.

    Saves URLs to a JSON file to avoid re-uploading.
    """

    def __init__(self, cache_path: Path):
        self.cache_path = Path(cache_path)
        self._cache = {}
        self._load()

    def _load(self):
        if self.cache_path.exists():
            import json
            with open(self.cache_path, "r") as f:
                self._cache = json.load(f)

    def _save(self):
        import json
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.cache_path, "w") as f:
            json.dump(self._cache, f, indent=2)

    def get(self, anchor_path: Path) -> Optional[str]:
        """Get cached URL for anchor, if exists and not expired."""
        key = str(anchor_path.resolve())
        return self._cache.get(key)

    def set(self, anchor_path: Path, url: str):
        """Cache URL for anchor."""
        key = str(anchor_path.resolve())
        self._cache[key] = url
        self._save()

    def get_or_upload(
        self,
        anchor_path: Path,
        api_key: Optional[str] = None,
    ) -> str:
        """Get cached URL or upload and cache."""
        cached = self.get(anchor_path)
        if cached:
            logger.debug(f"Using cached URL for {anchor_path.name}")
            return cached

        url = upload_to_imgbb(anchor_path, api_key=api_key)
        self.set(anchor_path, url)
        return url
