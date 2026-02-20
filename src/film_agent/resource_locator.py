"""Helpers for locating non-code resources in dev and packaged installs."""

from __future__ import annotations

import os
from pathlib import Path


_PACKAGE_ROOT = Path(__file__).resolve().parent
_DEFAULT_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_EMBEDDED_ROOT = _PACKAGE_ROOT / "resources"


def _dedupe_paths(paths: list[Path]) -> list[Path]:
    seen: set[str] = set()
    out: list[Path] = []
    for path in paths:
        key = str(path)
        if key in seen:
            continue
        out.append(path)
        seen.add(key)
    return out


def _resource_candidates(resource_name: str) -> list[Path]:
    env_name = f"FILM_AGENT_{resource_name.upper()}_DIR"
    paths: list[Path] = []

    env_val = os.environ.get(env_name)
    if env_val:
        paths.append(Path(env_val).expanduser())

    paths.append(_DEFAULT_PROJECT_ROOT / resource_name)

    cwd = Path.cwd().resolve()
    for parent in (cwd, *cwd.parents):
        paths.append(parent / resource_name)

    paths.append(_EMBEDDED_ROOT / resource_name)
    return _dedupe_paths(paths)


def find_resource_dir(resource_name: str) -> Path:
    for path in _resource_candidates(resource_name):
        if path.is_dir():
            return path
    searched = ", ".join(str(path) for path in _resource_candidates(resource_name))
    raise FileNotFoundError(f"Could not find '{resource_name}' directory. Searched: {searched}")

