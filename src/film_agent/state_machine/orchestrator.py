"""Manual orchestration services (file-based state machine)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from film_agent.config import RunConfig, load_config
from film_agent.constants import RunState
from film_agent.gates.common import report_path, write_report
from film_agent.gates.gate0 import evaluate_gate0
from film_agent.gates.gate1 import evaluate_gate1
from film_agent.gates.gate2 import evaluate_gate2
from film_agent.gates.gate3 import evaluate_gate3
from film_agent.gates.gate4 import evaluate_gate4
from film_agent.io.artifact_store import ArtifactError, submit_artifact
from film_agent.io.hashing import sha256_file
from film_agent.io.json_io import load_json
from film_agent.io.locking import lock_preprod_artifacts
from film_agent.schemas.artifacts import FinalScorecard, GateReport
from film_agent.state_machine.state_store import (
    RunStateData,
    append_event,
    ensure_run_layout,
    load_state,
    new_state,
    run_dir,
    save_state,
    start_next_iteration,
)


@dataclass
class CommandResult:
    run_id: str
    state: str
    detail: dict


def create_run(base_dir: Path, config_path: Path) -> CommandResult:
    resolved_config_path = config_path.expanduser().resolve()
    config = load_config(resolved_config_path)
    state = new_state(base_dir, resolved_config_path, config)
    path = run_dir(base_dir, state.run_id)
    ensure_run_layout(path)

    resolved_refs: list[str] = []
    ref_hashes: dict[str, str] = {}
    ref_catalog: list[dict[str, object]] = []
    for index, item in enumerate(config.reference_image_entries(), start=1):
        ref_path = Path(item.path).expanduser()
        if not ref_path.is_absolute():
            ref_path = resolved_config_path.parent / ref_path
        ref_path = ref_path.resolve()
        if not ref_path.exists():
            raise ValueError(f"Reference image not found: {ref_path}")
        resolved = str(ref_path)
        resolved_refs.append(resolved)
        checksum = sha256_file(ref_path)
        ref_hashes[resolved] = checksum
        ref_catalog.append(
            {
                "id": item.id or f"ref_{index:02d}",
                "path": resolved,
                "tags": list(item.tags),
                "notes": item.notes,
                "sha256": checksum,
            }
        )
    state.reference_images = resolved_refs
    state.reference_image_hashes = ref_hashes
    state.reference_image_catalog = ref_catalog

    save_state(path, state)
    append_event(path, "run_created", {"run_id": state.run_id, "config_path": str(resolved_config_path)})
    return CommandResult(state.run_id, state.current_state, {"path": str(path)})


def _load_run(base_dir: Path, run_id: str) -> tuple[Path, RunStateData, RunConfig]:
    path = run_dir(base_dir, run_id)
    state = load_state(path)
    config = load_config(Path(state.config_path))
    return path, state, config


def run_gate0(base_dir: Path, run_id: str) -> CommandResult:
    path, state, config = _load_run(base_dir, run_id)
    report = evaluate_gate0(state, config)
    out = write_report(path, report)
    state.gate_status["gate0"] = "passed" if report.passed else "failed"

    if report.passed:
        state.current_state = RunState.COLLECT_SHOWRUNNER
    else:
        state.current_state = RunState.FAILED

    save_state(path, state)
    append_event(path, "gate_validated", {"gate": "gate0", "passed": report.passed, "report": str(out)})
    return CommandResult(run_id, state.current_state, {"report": str(out), "metrics": report.metrics})


def submit_agent(base_dir: Path, run_id: str, agent: str, artifact_file: Path) -> CommandResult:
    path, state, _config = _load_run(base_dir, run_id)
    _check_agent_allowed_for_state(state, agent)

    try:
        submitted = submit_artifact(path, state, agent, artifact_file)
    except ArtifactError:
        raise

    lock_path: str | None = None
    if state.current_state == RunState.LOCK_PREPROD:
        lock = lock_preprod_artifacts(path, state)
        lock_path = str(lock)
        state.current_state = RunState.FINAL_RENDER
        append_event(path, "preprod_locked", {"iteration": state.current_iteration, "lock_path": str(lock)})

    save_state(path, state)
    return CommandResult(
        run_id=run_id,
        state=state.current_state,
        detail={
            "submitted": submitted,
            "lock_path": lock_path,
            "current_iteration": state.current_iteration,
        },
    )


def validate_gate(base_dir: Path, run_id: str, gate: int) -> CommandResult:
    if gate not in (1, 2, 3, 4):
        raise ValueError("gate must be one of: 1, 2, 3, 4")

    path, state, config = _load_run(base_dir, run_id)
    report: GateReport
    scorecard: FinalScorecard | None = None

    if gate == 1:
        _ensure_state(state, {RunState.GATE1})
        report = evaluate_gate1(path, state, config)
        _apply_gate1_transition(path, state, config, report)
    elif gate == 2:
        _ensure_state(state, {RunState.GATE2})
        report = evaluate_gate2(path, state, config)
        _apply_gate2_transition(path, state, config, report)
    elif gate == 3:
        _ensure_state(state, {RunState.GATE3})
        report = evaluate_gate3(path, state, config)
        _apply_gate3_transition(path, state, config, report)
    else:
        _ensure_state(state, {RunState.FINAL_RENDER, RunState.GATE4})
        report, scorecard = evaluate_gate4(path, state, config)
        _apply_gate4_transition(state, report)

    out = write_report(path, report)
    append_event(path, "gate_validated", {"gate": report.gate, "passed": report.passed, "report": str(out)})

    if scorecard:
        score_path = path / "gate_reports" / f"final_scorecard.iter-{state.current_iteration:02d}.json"
        from film_agent.io.json_io import dump_canonical_json  # local import to avoid cycle

        dump_canonical_json(score_path, scorecard.model_dump(mode="json"))

    save_state(path, state)
    detail = {"report": str(out), "metrics": report.metrics}
    if scorecard:
        detail["final_scorecard"] = scorecard.model_dump(mode="json")
    return CommandResult(run_id=run_id, state=state.current_state, detail=detail)


def _apply_gate1_transition(path: Path, state: RunStateData, config: RunConfig, report: GateReport) -> None:
    state.gate_status["gate1"] = "passed" if report.passed else "failed"
    if report.passed:
        state.current_state = RunState.COLLECT_DIRECTION
        return
    state.retry_counts["gate1"] += 1
    if state.retry_counts["gate1"] > config.retry_limits.gate1:
        state.current_state = RunState.FAILED
        return
    start_next_iteration(path, state, reason="gate1_failed", carry_forward=False)
    state.current_state = RunState.COLLECT_SHOWRUNNER


def _apply_gate2_transition(path: Path, state: RunStateData, config: RunConfig, report: GateReport) -> None:
    state.gate_status["gate2"] = "passed" if report.passed else "failed"
    if report.passed:
        state.current_state = RunState.COLLECT_DANCE_MAPPING
        return
    state.retry_counts["gate2"] += 1
    if state.retry_counts["gate2"] > config.retry_limits.gate2:
        state.current_state = RunState.FAILED
        return
    start_next_iteration(path, state, reason="gate2_failed", carry_forward=True)
    state.current_state = RunState.COLLECT_DIRECTION


def _apply_gate3_transition(path: Path, state: RunStateData, config: RunConfig, report: GateReport) -> None:
    state.gate_status["gate3"] = "passed" if report.passed else "failed"
    if report.passed:
        state.current_state = RunState.COLLECT_CINEMATOGRAPHY
        return

    state.retry_counts["gate3"] += 1
    if state.retry_counts["gate3"] > config.retry_limits.gate3:
        state.current_state = RunState.FAILED
        return

    start_next_iteration(path, state, reason="gate3_failed", carry_forward=True)
    state.current_state = RunState.COLLECT_DANCE_MAPPING


def _apply_gate4_transition(state: RunStateData, report: GateReport) -> None:
    state.gate_status["gate4"] = "passed" if report.passed else "failed"
    state.current_state = RunState.COMPLETE if report.passed else RunState.FAILED


def _load_gate_report(path: Path, gate: str, iteration: int) -> GateReport:
    candidate = report_path(path, gate, iteration)
    if candidate.exists():
        return GateReport.model_validate(load_json(candidate))

    fallback = GateReport(
        gate=gate,
        passed=False,
        iteration=iteration,
        metrics={},
        reasons=[f"{gate} report missing for iteration {iteration}."],
        fix_instructions=["Run gate validation for this iteration first."],
    )
    return fallback


def _ensure_state(state: RunStateData, allowed: set[str]) -> None:
    if state.current_state not in allowed:
        accepted = ", ".join(sorted(allowed))
        raise ValueError(f"Current state {state.current_state} does not allow this operation. Expected: {accepted}")


def _check_agent_allowed_for_state(state: RunStateData, agent: str) -> None:
    expected = {
        RunState.COLLECT_SHOWRUNNER: {"showrunner"},
        RunState.COLLECT_DIRECTION: {"direction"},
        RunState.COLLECT_DANCE_MAPPING: {"dance_mapping"},
        RunState.COLLECT_CINEMATOGRAPHY: {"cinematography"},
        RunState.COLLECT_AUDIO: {"audio"},
        RunState.FINAL_RENDER: {"dryrun_metrics", "final_metrics", "timeline", "render_package"},
    }
    allowed = expected.get(state.current_state, set())
    if not allowed or agent not in allowed:
        raise ValueError(
            f"Agent '{agent}' cannot submit in state '{state.current_state}'. "
            f"Allowed now: {sorted(allowed)}"
        )


def command_result_payload(result: CommandResult) -> dict:
    return {"run_id": result.run_id, "state": result.state, "detail": result.detail}
