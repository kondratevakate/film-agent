#!/usr/bin/env python
"""Export JSON Schemas for artifact contracts."""

from __future__ import annotations

import json
from pathlib import Path

from film_agent.schemas.registry import AGENT_ARTIFACTS


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    out_dir = root / "schemas"
    out_dir.mkdir(parents=True, exist_ok=True)
    for agent, entry in AGENT_ARTIFACTS.items():
        schema = entry.model.model_json_schema()
        out_path = out_dir / f"{agent}.schema.json"
        out_path.write_text(json.dumps(schema, indent=2, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
        print("wrote", out_path)


if __name__ == "__main__":
    main()
