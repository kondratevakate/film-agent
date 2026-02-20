"""Gate 2: Shot sheet validity + cinematic constraints."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from film_agent.config import RunConfig
from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.schemas.artifacts import CinematographyPackage, GateReport
from film_agent.state_machine.state_store import RunStateData


def evaluate_gate2(run_path: Path, state: RunStateData, config: RunConfig) -> GateReport:
    reasons: list[str] = []
    fixes: list[str] = []

    cinematography = load_artifact_for_agent(run_path, state, "cinematography")
    if cinematography is None:
        reasons.append("Missing cinematography artifact.")
        fixes.append("Submit CinematographyPackage before running Gate2.")
        return GateReport(
            gate="gate2",
            passed=False,
            iteration=state.current_iteration,
            metrics={
                "schema_completeness_pct": 0.0,
                "continuity_violations": 999,
                "variety_score": 0.0,
                "max_consecutive_identical_framing": 999,
            },
            reasons=reasons,
            fix_instructions=fixes,
        )

    cinematography = cast(CinematographyPackage, cinematography)
    shots = cinematography.shots
    schema_completeness_pct = 100.0

    identity_tokens: dict[str, str] = {}
    continuity_violations = 0
    for shot in shots:
        existing = identity_tokens.get(shot.character)
        if existing is None:
            identity_tokens[shot.character] = shot.identity_token
        elif existing != shot.identity_token:
            continuity_violations += 1
            reasons.append(f"Identity token drift for character {shot.character}.")

    for idx in range(1, len(shots)):
        prev = shots[idx - 1]
        cur = shots[idx]
        if prev.beat_id == cur.beat_id and prev.location != cur.location and not cur.continuity_reset:
            continuity_violations += 1
            reasons.append(
                f"Location jump without continuity_reset between {prev.shot_id} and {cur.shot_id}."
            )

    framing_count: dict[str, int] = {}
    for shot in shots:
        framing_count[shot.framing] = framing_count.get(shot.framing, 0) + 1

    distinct_framings = len(framing_count)
    variety_score = min(100.0, (distinct_framings / max(config.thresholds.shot_variety_min_types, 1)) * 100.0)
    max_streak = _max_identical_streak([shot.framing for shot in shots])

    if continuity_violations > 0:
        fixes.append("Fix identity/location continuity in shot sheets.")
    if variety_score < config.thresholds.variety_score_threshold:
        reasons.append("Shot variety score below threshold.")
        fixes.append("Increase framing diversity across the sequence.")
    if max_streak > config.thresholds.max_consecutive_identical_framing:
        reasons.append("Too many consecutive shots with identical framing.")
        fixes.append("Break framing streaks with alternate shot sizes/camera plans.")

    passed = (
        schema_completeness_pct == 100.0
        and continuity_violations == 0
        and variety_score >= config.thresholds.variety_score_threshold
        and max_streak <= config.thresholds.max_consecutive_identical_framing
    )

    return GateReport(
        gate="gate2",
        passed=passed,
        iteration=state.current_iteration,
        metrics={
            "schema_completeness_pct": schema_completeness_pct,
            "continuity_violations": continuity_violations,
            "variety_score": round(variety_score, 2),
            "distinct_framing_types": distinct_framings,
            "max_consecutive_identical_framing": max_streak,
        },
        reasons=_unique(reasons),
        fix_instructions=_unique(fixes),
    )


def _max_identical_streak(values: list[str]) -> int:
    if not values:
        return 0
    current = 1
    maximum = 1
    for idx in range(1, len(values)):
        if values[idx] == values[idx - 1]:
            current += 1
            maximum = max(maximum, current)
        else:
            current = 1
    return maximum


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out
