"""Gate 3: dry-run quality checks."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from film_agent.config import RunConfig
from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.schemas.artifacts import DryRunMetrics, GateReport
from film_agent.state_machine.state_store import RunStateData


def evaluate_gate3(run_path: Path, state: RunStateData, config: RunConfig) -> GateReport:
    reasons: list[str] = []
    fixes: list[str] = []

    dryrun = load_artifact_for_agent(run_path, state, "dryrun_metrics")
    if dryrun is None:
        reasons.append("Missing dryrun_metrics artifact.")
        fixes.append("Submit dryrun metrics JSON before Gate3 validation.")
        return GateReport(
            gate="gate3",
            passed=False,
            iteration=state.current_iteration,
            metrics={},
            reasons=reasons,
            fix_instructions=fixes,
        )

    dryrun = cast(DryRunMetrics, dryrun)
    t = config.thresholds

    if dryrun.videoscore2 < t.videoscore2_threshold:
        reasons.append("VideoScore2 below threshold.")
        fixes.append("Adjust prompts/shots and rerun cheap dry-runs.")
    if dryrun.vbench2_physics < t.vbench2_physics_floor:
        reasons.append("VBench2 physics below floor.")
        fixes.append("Reduce implausible motion/object interactions.")
    if dryrun.identity_drift > t.identity_drift_ceiling:
        reasons.append("Identity drift above ceiling.")
        fixes.append("Strengthen identity tokens/shot continuity prompts.")
    if dryrun.blocking_issues > 0:
        reasons.append("Blocking issues reported by QA.")
        fixes.append("Resolve blocking issues before final one-shot render.")

    passed = (
        dryrun.videoscore2 >= t.videoscore2_threshold
        and dryrun.vbench2_physics >= t.vbench2_physics_floor
        and dryrun.identity_drift <= t.identity_drift_ceiling
        and dryrun.blocking_issues == 0
    )

    return GateReport(
        gate="gate3",
        passed=passed,
        iteration=state.current_iteration,
        metrics={
            "videoscore2": dryrun.videoscore2,
            "vbench2_physics": dryrun.vbench2_physics,
            "identity_drift": dryrun.identity_drift,
            "blocking_issues": dryrun.blocking_issues,
            "videoscore2_threshold": t.videoscore2_threshold,
            "vbench2_physics_floor": t.vbench2_physics_floor,
            "identity_drift_ceiling": t.identity_drift_ceiling,
        },
        reasons=reasons,
        fix_instructions=fixes,
    )
