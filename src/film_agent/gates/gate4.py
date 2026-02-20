"""Gate 4: final acceptance + final scoring."""

from __future__ import annotations

from pathlib import Path

from film_agent.config import RunConfig
from film_agent.gates.scoring import (
    build_final_scorecard,
    compute_audio_sync,
    compute_cinematic_quality,
    compute_consistency,
    compute_dance_mapping_score,
    compute_science_clarity,
)
from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.schemas.artifacts import (
    BeatBible,
    CinematographyPackage,
    DanceMappingSpec,
    FinalMetrics,
    FinalScorecard,
    GateReport,
    UserDirectionPack,
)
from film_agent.state_machine.state_store import RunStateData


def evaluate_gate4(run_path: Path, state: RunStateData, config: RunConfig, gate1_report: GateReport, gate2_report: GateReport) -> tuple[GateReport, FinalScorecard]:
    reasons: list[str] = []
    fixes: list[str] = []

    dryrun = load_artifact_for_agent(run_path, state, "dryrun_metrics")
    final_metrics = load_artifact_for_agent(run_path, state, "final_metrics")
    beat_bible = load_artifact_for_agent(run_path, state, "showrunner")
    direction_pack = load_artifact_for_agent(run_path, state, "direction")
    dance_mapping = load_artifact_for_agent(run_path, state, "dance_mapping")
    cinematography = load_artifact_for_agent(run_path, state, "cinematography")
    audio = load_artifact_for_agent(run_path, state, "audio")

    if any(item is None for item in (dryrun, final_metrics, beat_bible, direction_pack, dance_mapping, cinematography, audio)):
        reasons.append("Missing one or more required artifacts for Gate4 scoring.")
        fixes.append("Ensure dryrun_metrics, final_metrics and pre-production artifacts are submitted.")
        empty = FinalScorecard(
            science_clarity=0.0,
            dance_mapping=0.0,
            cinematic_quality=0.0,
            consistency=0.0,
            audio_sync=0.0,
            final_score=0.0,
        )
        return (
            GateReport(
                gate="gate4",
                passed=False,
                iteration=state.current_iteration,
                metrics={},
                reasons=reasons,
                fix_instructions=fixes,
            ),
            empty,
        )

    assert isinstance(final_metrics, FinalMetrics)
    assert isinstance(beat_bible, BeatBible)
    assert isinstance(direction_pack, UserDirectionPack)
    assert isinstance(dance_mapping, DanceMappingSpec)
    assert isinstance(cinematography, CinematographyPackage)

    t = config.thresholds
    dryrun_video = float(getattr(dryrun, "videoscore2"))
    dryrun_physics = float(getattr(dryrun, "vbench2_physics"))

    video_regression = dryrun_video - final_metrics.videoscore2
    physics_regression = dryrun_physics - final_metrics.vbench2_physics

    if final_metrics.videoscore2 < t.videoscore2_threshold:
        reasons.append("Final VideoScore2 below threshold.")
        fixes.append("Tune final render prompts/settings and rerun as new run.")
    if final_metrics.vbench2_physics < t.vbench2_physics_floor:
        reasons.append("Final VBench2 physics below floor.")
        fixes.append("Fix motion plausibility before final render.")
    if final_metrics.identity_drift > t.identity_drift_ceiling:
        reasons.append("Final identity drift above ceiling.")
        fixes.append("Tighten identity constraints in generation scripts.")
    if video_regression > t.regression_epsilon or physics_regression > t.regression_epsilon:
        reasons.append("Final regression exceeds epsilon versus dry-run.")
        fixes.append("Investigate prompt/model/settings drift between dry-run and final.")

    concept_coverage = float(gate1_report.metrics.get("concept_coverage_pct", 0.0))
    critical_errors = int(gate1_report.metrics.get("critical_science_errors", 0))
    science_clarity = compute_science_clarity(beat_bible, concept_coverage, critical_errors)
    dance_score = compute_dance_mapping_score(beat_bible, dance_mapping, direction_pack)

    continuity_violations = int(gate2_report.metrics.get("continuity_violations", 0))
    variety_score = float(gate2_report.metrics.get("variety_score", 0.0))
    cinematic_quality = compute_cinematic_quality(cinematography, continuity_violations, variety_score)
    consistency = compute_consistency(final_metrics)
    audio_sync = compute_audio_sync(audio, final_metrics)
    scorecard = build_final_scorecard(
        science_clarity=science_clarity,
        dance_mapping=dance_score,
        cinematic_quality=cinematic_quality,
        consistency=consistency,
        audio_sync=audio_sync,
    )

    passed = not reasons
    report = GateReport(
        gate="gate4",
        passed=passed,
        iteration=state.current_iteration,
        metrics={
            "videoscore2": final_metrics.videoscore2,
            "vbench2_physics": final_metrics.vbench2_physics,
            "identity_drift": final_metrics.identity_drift,
            "video_regression": round(video_regression, 4),
            "physics_regression": round(physics_regression, 4),
            "epsilon": t.regression_epsilon,
            "science_clarity": round(scorecard.science_clarity, 2),
            "dance_mapping": round(scorecard.dance_mapping, 2),
            "cinematic_quality": round(scorecard.cinematic_quality, 2),
            "consistency": round(scorecard.consistency, 2),
            "audio_sync": round(scorecard.audio_sync, 2),
            "final_score": round(scorecard.final_score, 2),
        },
        reasons=reasons,
        fix_instructions=fixes,
    )
    return report, scorecard
