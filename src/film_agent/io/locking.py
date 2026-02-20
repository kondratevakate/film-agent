"""Immutable lock manifests."""

from __future__ import annotations

from pathlib import Path

from film_agent.constants import REQUIRED_PREPROD_ARTIFACTS
from film_agent.io.hashing import sha256_file
from film_agent.io.hashing import sha256_json
from film_agent.io.json_io import dump_canonical_json
from film_agent.state_machine.state_store import RunStateData, iteration_key, utc_now_iso


def lock_preprod_artifacts(run_path: Path, state: RunStateData) -> Path:
    iter_key = iteration_key(state.current_iteration)
    record = state.iterations[iter_key]

    entries: list[dict[str, str]] = []
    artifact_hashes: dict[str, str] = {}
    for agent in REQUIRED_PREPROD_ARTIFACTS:
        item = record.artifacts.get(agent)
        if not item:
            raise ValueError(f"Missing pre-production artifact for '{agent}'.")
        path = Path(item.path)
        artifact_hash = sha256_file(path)
        artifact_hashes[agent] = artifact_hash
        entries.append(
            {
                "agent": agent,
                "path": str(path),
                "sha256": artifact_hash,
            }
        )

    spec_hash = sha256_json(
        {
            "run_id": state.run_id,
            "iteration": state.current_iteration,
            "config_hash": state.config_hash,
            "active_video_provider": state.active_video_provider,
            "artifacts": artifact_hashes,
        }
    )
    lock = {
        "run_id": state.run_id,
        "iteration": state.current_iteration,
        "created_at": utc_now_iso(),
        "direction_pack_id": state.latest_direction_pack_id,
        "active_video_provider": state.active_video_provider,
        "spec_hash": spec_hash,
        "artifacts": entries,
    }
    out = run_path / "locks" / f"preprod.{iter_key}.lock.json"
    dump_canonical_json(out, lock)
    state.preprod_locked_iteration = state.current_iteration
    state.locked_spec_hash = spec_hash
    return out
