"""Gate 1: script quality and structural sanity checks."""

from __future__ import annotations

from pathlib import Path
import re
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
                "adjacent_character_violations": 999,
                "multi_action_lines": 999,
                "complex_visual_without_closeup": 999,
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
    if line_count < 10:
        reasons.append("Script is too sparse for a coherent short film.")
        fixes.append("Provide at least 10 timed lines (action/dialogue).")

    adjacent_character_violations = _count_adjacent_primary_character_violations(script)
    if adjacent_character_violations > 0:
        reasons.append("Same primary character appears in adjacent lines without separator shots.")
        fixes.append("Insert a different character or non-character separator line between repeated character shots.")

    multi_action_lines = sum(1 for line in script.lines if line.kind == "action" and _has_multiple_primary_actions(line.text))
    if multi_action_lines > 0:
        reasons.append("Some action lines appear to contain multiple chained primary actions.")
        fixes.append("Split chained actions into separate lines with one primary action each.")

    complex_visual_without_closeup = sum(1 for line in script.lines if _complex_visual_without_closeup(line.text))
    if complex_visual_without_closeup > 0:
        reasons.append("Screen/text/photo/interface details are used without close-up framing cues.")
        fixes.append("Mark those lines as close-up to improve generation reliability.")

    passed = (
        duration_ok
        and not undeclared_speakers
        and placeholder_lines == 0
        and line_count >= 10
        and adjacent_character_violations == 0
        and multi_action_lines == 0
        and complex_visual_without_closeup == 0
    )

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
            "adjacent_character_violations": adjacent_character_violations,
            "multi_action_lines": multi_action_lines,
            "complex_visual_without_closeup": complex_visual_without_closeup,
            "duration_target_s": config.duration_target_s,
        },
        reasons=reasons,
        fix_instructions=fixes,
    )


def _count_adjacent_primary_character_violations(script: ScriptArtifact) -> int:
    declared = [name.strip() for name in script.characters if name.strip()]
    violations = 0
    prev_primary: str | None = None

    for line in script.lines:
        current = _primary_character_for_line(line.kind, line.text, line.speaker, declared)
        if prev_primary and current and prev_primary.casefold() == current.casefold():
            violations += 1
        prev_primary = current
    return violations


def _primary_character_for_line(kind: str, text: str, speaker: str | None, declared: list[str]) -> str | None:
    if kind == "dialogue":
        value = (speaker or "").strip()
        return value or None

    text_lower = text.casefold()
    found = [name for name in declared if name.casefold() in text_lower]
    if len(found) == 1:
        return found[0]
    return None


def _has_multiple_primary_actions(text: str) -> bool:
    lower = text.casefold()
    sentence_markers = len(re.findall(r"[.!?]", text))
    chained_transitions = len(re.findall(r"\b(and then|then|while|before|after)\b", lower))
    semicolon_split = ";" in text
    return sentence_markers > 1 or chained_transitions > 1 or semicolon_split


def _complex_visual_without_closeup(text: str) -> bool:
    lower = text.casefold()
    detail_tokens = (
        "screen",
        "phone",
        "interface",
        "text",
        "label",
        "photo",
        "overlay",
        "document",
    )
    closeup_tokens = ("close-up", "close up", "macro", "extreme close")
    return any(token in lower for token in detail_tokens) and not any(token in lower for token in closeup_tokens)
