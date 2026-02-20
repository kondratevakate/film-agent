"""Gate 1: Beat bible completeness and scientific correctness."""

from __future__ import annotations

from pathlib import Path

from film_agent.config import RunConfig
from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.schemas.artifacts import BeatBible, DanceMappingSpec, GateReport, UserDirectionPack
from film_agent.state_machine.state_store import RunStateData


def _concept_coverage(beats: BeatBible, concepts: list[str]) -> float:
    if not concepts:
        return 100.0
    claims = " ".join((f"{beat.science_claim} {beat.dance_metaphor}").lower() for beat in beats.beats)
    hits = sum(1 for concept in concepts if concept.lower() in claims)
    return (hits / len(concepts)) * 100.0


def evaluate_gate1(run_path: Path, state: RunStateData, config: RunConfig) -> GateReport:
    reasons: list[str] = []
    fixes: list[str] = []

    beat_bible = load_artifact_for_agent(run_path, state=state, agent="showrunner")
    if beat_bible is None:
        reasons.append("Missing BeatBible artifact.")
    direction = load_artifact_for_agent(run_path, state=state, agent="direction")
    if direction is None:
        reasons.append("Missing UserDirectionPack artifact.")
    dance_mapping = load_artifact_for_agent(run_path, state=state, agent="dance_mapping")
    if dance_mapping is None:
        reasons.append("Missing DanceMappingSpec artifact.")

    if reasons:
        fixes.append("Submit missing required pre-production artifacts.")
        return GateReport(
            gate="gate1",
            passed=False,
            iteration=state.current_iteration,
            metrics={
                "all_required_fields_present": 0.0,
                "coverage_ok": False,
                "critical_science_errors": 999,
                "concept_coverage_pct": 0.0,
            },
            reasons=reasons,
            fix_instructions=fixes,
        )

    assert isinstance(beat_bible, BeatBible)
    assert isinstance(direction, UserDirectionPack)
    assert isinstance(dance_mapping, DanceMappingSpec)

    total_duration = sum(beat.end_s - beat.start_s for beat in beat_bible.beats)
    coverage_ok = 90.0 <= total_duration <= 105.0
    if not coverage_ok:
        reasons.append(f"Beat duration total {total_duration:.2f}s is outside [90, 105].")
        fixes.append("Adjust beat timings so total duration is between 90 and 105 seconds.")

    critical_errors = sum(1 for beat in beat_bible.beats if beat.science_status == "critical_error")
    if critical_errors > 0:
        reasons.append(f"Critical science errors detected: {critical_errors}.")
        fixes.append("Fix critical science claims in BeatBible.")

    concept_coverage_pct = _concept_coverage(beat_bible, config.core_concepts)
    if concept_coverage_pct < 100.0:
        reasons.append("Not all core concepts are covered by BeatBible.")
        fixes.append("Add missing core concepts to at least one beat science claim.")

    beat_ids = {beat.beat_id for beat in beat_bible.beats}
    mapped_ids = {mapping.beat_id for mapping in dance_mapping.mappings}
    mapping_coverage_pct = (len(beat_ids & mapped_ids) / max(len(beat_ids), 1)) * 100.0
    if mapping_coverage_pct < 100.0:
        reasons.append("Dance mapping does not cover every beat.")
        fixes.append("Add DanceMapping entries for each beat_id in BeatBible.")

    direction_nonempty = bool(direction.iteration_goal.strip())
    if not direction_nonempty:
        reasons.append("UserDirectionPack.iteration_goal is empty.")
        fixes.append("Provide explicit iteration_goal before dance mapping.")

    all_required = 100.0
    passed = coverage_ok and critical_errors == 0 and concept_coverage_pct == 100.0 and mapping_coverage_pct == 100.0 and direction_nonempty
    if not passed and not fixes:
        fixes.append("Review Gate1 metrics and update pre-production artifacts.")

    return GateReport(
        gate="gate1",
        passed=passed,
        iteration=state.current_iteration,
        metrics={
            "beat_duration_total_s": round(total_duration, 4),
            "coverage_ok": coverage_ok,
            "critical_science_errors": critical_errors,
            "concept_coverage_pct": round(concept_coverage_pct, 2),
            "dance_mapping_coverage_pct": round(mapping_coverage_pct, 2),
            "all_required_fields_present": all_required,
            "direction_pack_id": state.latest_direction_pack_id,
        },
        reasons=reasons,
        fix_instructions=fixes,
    )
