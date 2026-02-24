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
from film_agent.gates.story_qa import evaluate_story_qa
from film_agent.io.artifact_store import ArtifactError, submit_artifact
from film_agent.io.hashing import sha256_file
from film_agent.io.json_io import load_json
from film_agent.io.locking import lock_preprod_artifacts
from film_agent.io.transcript_logger import load_transcript_metrics
from film_agent.schemas.artifacts import EvalMetrics, FinalScorecard, GateReport
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

    # Map gates to the role that was just processed
    gate_to_role = {1: "showrunner", 2: "direction", 3: "dance_mapping", 4: None}

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

    # Enrich report with eval metrics from transcript (if available)
    role = gate_to_role.get(gate)
    if role:
        transcript_data = load_transcript_metrics(path, state.current_iteration, role)
        if transcript_data:
            report.eval_metrics = EvalMetrics(
                total_tokens=transcript_data["total_tokens"],
                total_latency_ms=transcript_data["total_latency_ms"],
                num_llm_calls=transcript_data["num_llm_calls"],
                num_refinement_rounds=transcript_data["num_refinement_rounds"],
                was_approved=transcript_data["was_approved"],
                transcript_path=transcript_data["transcript_path"],
            )

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


def run_story_qa(base_dir: Path, run_id: str, save_result: bool = True) -> CommandResult:
    """Evaluate script against 14 storytelling criteria (Story QA gate)."""
    path, state, config = _load_run(base_dir, run_id)

    report, story_qa_result = evaluate_story_qa(path, state, config)
    out = write_report(path, report)

    if save_result and story_qa_result is not None:
        # Save StoryQAResult artifact
        from film_agent.io.json_io import dump_canonical_json

        result_path = (
            path / "iterations" / f"iter-{state.current_iteration:02d}" / "artifacts" / "story_qa.json"
        )
        dump_canonical_json(result_path, story_qa_result.model_dump(mode="json"))

    append_event(
        path,
        "story_qa_evaluated",
        {
            "passed": report.passed,
            "overall_score": story_qa_result.overall_score if story_qa_result else 0,
            "blocking_issues": story_qa_result.blocking_issues if story_qa_result else [],
            "report": str(out),
        },
    )

    detail = {
        "report": str(out),
        "passed": report.passed,
        "metrics": report.metrics,
    }
    if story_qa_result:
        detail["overall_score"] = story_qa_result.overall_score
        detail["blocking_issues"] = story_qa_result.blocking_issues
        detail["recommendations"] = story_qa_result.recommendations

    return CommandResult(run_id=run_id, state=state.current_state, detail=detail)


def apply_patch(base_dir: Path, run_id: str, patch_file: Path, dry_run: bool = False) -> dict:
    """Apply a manual patch to an artifact deterministically.

    Args:
        base_dir: Base directory for runs
        run_id: Run identifier
        patch_file: Path to patch JSON file
        dry_run: If True, validate without applying

    Returns:
        Dict with patch result details
    """
    import json
    import copy

    from film_agent.schemas.artifacts import PatchArtifact
    from film_agent.io.json_io import dump_canonical_json
    from film_agent.io.hashing import sha256_json

    path, state, _config = _load_run(base_dir, run_id)

    # Load and validate patch
    patch_data = json.loads(patch_file.read_text(encoding="utf-8"))
    patch = PatchArtifact.model_validate(patch_data)

    # Map artifact type to agent name and file
    artifact_map = {
        "script": ("showrunner", "script.json"),
        "script_review": ("direction", "script_review.json"),
        "image_prompt_package": ("dance_mapping", "image_prompt_package.json"),
        "av_prompt_package": ("audio", "av_prompt_package.json"),
    }

    if patch.target_artifact not in artifact_map:
        raise ValueError(f"Unknown artifact type: {patch.target_artifact}")

    _agent, filename = artifact_map[patch.target_artifact]

    # Load target artifact
    artifact_path = (
        path / "iterations" / f"iter-{patch.target_iteration:02d}" / "artifacts" / filename
    )
    if not artifact_path.exists():
        raise ValueError(f"Target artifact not found: {artifact_path}")

    artifact_data = json.loads(artifact_path.read_text(encoding="utf-8"))
    current_hash = sha256_json(artifact_data)

    # Verify hash matches
    if current_hash != patch.target_artifact_hash:
        raise ValueError(
            f"Artifact hash mismatch. Expected: {patch.target_artifact_hash}, "
            f"Got: {current_hash}. Artifact may have been modified."
        )

    # Apply operations
    patched_data = copy.deepcopy(artifact_data)
    applied_ops = []

    for op in patch.operations:
        try:
            _apply_operation(patched_data, op.path, op.operation, op.old_value, op.new_value)
            applied_ops.append({"path": op.path, "operation": op.operation, "status": "applied"})
        except Exception as e:
            applied_ops.append({"path": op.path, "operation": op.operation, "status": "failed", "error": str(e)})
            if not dry_run:
                raise ValueError(f"Patch operation failed: {op.path} - {e}") from e

    new_hash = sha256_json(patched_data)

    result = {
        "run_id": run_id,
        "target_artifact": patch.target_artifact,
        "target_iteration": patch.target_iteration,
        "original_hash": current_hash,
        "new_hash": new_hash,
        "operations_count": len(patch.operations),
        "applied_operations": applied_ops,
        "dry_run": dry_run,
    }

    if dry_run:
        result["message"] = "Dry run completed. No changes written."
        return result

    # Write patched artifact
    dump_canonical_json(artifact_path, patched_data)

    # Log the patch event
    append_event(
        path,
        "patch_applied",
        {
            "artifact": patch.target_artifact,
            "iteration": patch.target_iteration,
            "original_hash": current_hash,
            "new_hash": new_hash,
            "operations": len(patch.operations),
            "rationale": patch.rationale,
            "author": patch.author,
        },
    )

    result["message"] = "Patch applied successfully."
    return result


def _apply_operation(data: dict, path: str, operation: str, old_value, new_value) -> None:
    """Apply a single patch operation to data.

    Supports JSON-path-like notation: "lines[5].text", "logline", etc.
    """
    import re

    # Parse path into components
    # e.g., "lines[5].text" -> ["lines", 5, "text"]
    components = []
    for part in re.split(r"\.|\[|\]", path):
        if not part:
            continue
        if part.isdigit():
            components.append(int(part))
        else:
            components.append(part)

    if not components:
        raise ValueError(f"Invalid path: {path}")

    # Navigate to parent
    current = data
    for comp in components[:-1]:
        if isinstance(comp, int):
            if not isinstance(current, list) or comp >= len(current):
                raise ValueError(f"Index {comp} out of range for path {path}")
            current = current[comp]
        else:
            if comp not in current:
                raise ValueError(f"Key '{comp}' not found for path {path}")
            current = current[comp]

    # Apply operation on final component
    final = components[-1]

    if operation == "replace":
        if isinstance(final, int):
            if old_value is not None and current[final] != old_value:
                raise ValueError(f"Old value mismatch at {path}")
            current[final] = new_value
        else:
            if old_value is not None and current.get(final) != old_value:
                raise ValueError(f"Old value mismatch at {path}")
            current[final] = new_value

    elif operation == "delete":
        if isinstance(final, int):
            del current[final]
        else:
            del current[final]

    elif operation == "insert":
        if isinstance(final, int):
            current.insert(final, new_value)
        else:
            current[final] = new_value

    else:
        raise ValueError(f"Unknown operation: {operation}")
