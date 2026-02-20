"""Shared gate helpers."""

from __future__ import annotations

from pathlib import Path

from film_agent.io.json_io import dump_canonical_json
from film_agent.schemas.artifacts import GateReport
from film_agent.state_machine.state_store import RunStateData, iteration_key


def report_path(run_path: Path, gate: str, iteration: int) -> Path:
    return run_path / "gate_reports" / f"{gate}.{iteration_key(iteration)}.json"


def write_report(run_path: Path, report: GateReport) -> Path:
    out = report_path(run_path, report.gate, report.iteration)
    dump_canonical_json(out, report.model_dump(mode="json"))
    return out


def get_iteration_artifact_path(state: RunStateData, agent: str) -> Path | None:
    key = iteration_key(state.current_iteration)
    record = state.iterations.get(key)
    if not record:
        return None
    item = record.artifacts.get(agent)
    if not item:
        return None
    return Path(item.path)
