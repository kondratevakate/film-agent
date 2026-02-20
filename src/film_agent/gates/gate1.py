"""Gate 1: script quality and structural sanity checks."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from film_agent.config import RunConfig
from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.schemas.artifacts import GateReport, ScriptArtifact
from film_agent.state_machine.state_store import RunStateData


def evaluate_gate1(run_path: Path, state: RunStateData, config: RunConfig) -> GateReport:
    reasons: list[str] = []
    fixes: list[str] = []

    script = load_artifact_for_agent(run_path, state=state, agent="showrunner")
    if script is None:
        reasons.append("Missing script artifact.")
        fixes.append("Submit script JSON before Gate1 validation.")
        return GateReport(
            gate="gate1",
            passed=False,
            iteration=state.current_iteration,
            metrics={
                "estimated_duration_s": 0.0,
                "duration_ok": False,
                "line_count": 0,
                "dialogue_lines": 0,
                "undeclared_speakers": 999,
                "placeholder_lines": 999,
            },
            reasons=reasons,
            fix_instructions=fixes,
        )

    script = cast(ScriptArtifact, script)

    estimated_duration_s = sum(line.est_duration_s for line in script.lines)
    duration_ok = 60.0 <= estimated_duration_s <= 120.0
    if not duration_ok:
        reasons.append(f"Estimated script duration {estimated_duration_s:.2f}s is outside [60, 120].")
        fixes.append("Trim or extend script timing so estimated duration fits 60-120 seconds.")

    declared_characters = {name.strip() for name in script.characters if name.strip()}
    undeclared_speakers = {
        (line.speaker or "").strip()
        for line in script.lines
        if line.kind == "dialogue" and (line.speaker or "").strip() and (line.speaker or "").strip() not in declared_characters
    }
    if undeclared_speakers:
        reasons.append("Dialogue contains speakers not listed in script.characters.")
        fixes.append("Add missing speakers to characters list or reassign dialogue speakers.")

    placeholder_lines = sum(
        1
        for line in script.lines
        if "todo" in line.text.lower() or "tbd" in line.text.lower() or "<" in line.text and ">" in line.text
    )
    if placeholder_lines > 0:
        reasons.append("Script still contains placeholder content (TODO/TBD/template markers).")
        fixes.append("Replace placeholders with final story text before promoting script.")

    line_count = len(script.lines)
    dialogue_lines = sum(1 for line in script.lines if line.kind == "dialogue")
    if line_count < 8:
        reasons.append("Script is too sparse for a coherent short film.")
        fixes.append("Provide at least 8 timed lines (action/dialogue).")

    passed = duration_ok and not undeclared_speakers and placeholder_lines == 0 and line_count >= 8

    return GateReport(
        gate="gate1",
        passed=passed,
        iteration=state.current_iteration,
        metrics={
            "estimated_duration_s": round(estimated_duration_s, 3),
            "duration_ok": duration_ok,
            "line_count": line_count,
            "dialogue_lines": dialogue_lines,
            "undeclared_speakers": len(undeclared_speakers),
            "placeholder_lines": placeholder_lines,
            "duration_target_s": config.duration_target_s,
        },
        reasons=reasons,
        fix_instructions=fixes,
    )
