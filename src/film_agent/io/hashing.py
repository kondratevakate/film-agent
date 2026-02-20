"""Hash helpers."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_json(data: Any) -> str:
    canonical = json.dumps(data, sort_keys=True, ensure_ascii=True, separators=(",", ":"))
    return sha256_bytes(canonical.encode("utf-8"))
