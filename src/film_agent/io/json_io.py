"""Stable JSON read/write helpers."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def dump_canonical_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=True)
    path.write_text(text + "\n", encoding="utf-8")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))
