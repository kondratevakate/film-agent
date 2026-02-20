"""Gate 1: script quality and structural sanity checks."""

from __future__ import annotations

from pathlib import Path
import re
from typing import cast

from film_agent.continuity import (
    character_consistency_pct,
    load_story_anchor,
    script_faithfulness_pct,
    title_matches_anchor,
)
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
                "adjacent_same_background_pairs": 999,
                "tight_spatial_transition_pairs": 999,
                "fine_grained_visual_elements": 999,
                "concept_alignment_pct": 0.0,
                "structure_complete": False,
                "story_anchor_present": False,
                "anchor_title_match": False,
                "character_consistency": 0.0,
                "script_faithfulness": 0.0,
                "narrative_coherence": 0.0,
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

    adjacent_same_background_pairs = _count_adjacent_same_background_pairs(script)
    if adjacent_same_background_pairs > 0:
        reasons.append("Adjacent lines repeat the same background, reducing shot-level diversity and reliability.")
        fixes.append("Alternate backgrounds or insert separator shots before returning to the same setting.")

    tight_spatial_transition_pairs = _count_tight_spatial_transition_pairs(script)
    if tight_spatial_transition_pairs > 0:
        reasons.append("Some adjacent lines imply tightly connected spatial transitions that are fragile in generation.")
        fixes.append("Avoid door-to-door or room-to-room adjacency jumps; use looser transition shots.")

    fine_grained_visual_elements = sum(1 for line in script.lines if _has_fine_grained_visual_elements(line.text))
    if fine_grained_visual_elements > 2:
        reasons.append("Script contains too many fine-grained visual elements for reliable generation.")
        fixes.append("Simplify tiny/textual/interface-heavy details and keep composition cleaner.")

    concept_alignment_pct = _concept_alignment_pct(config.core_concepts, script)
    concept_alignment_ok = concept_alignment_pct >= 75.0 if config.core_concepts else True
    if not concept_alignment_ok:
        reasons.append("Script does not sufficiently align with configured core concepts.")
        fixes.append("Reinforce core concepts explicitly in logline/theme and key lines.")

    structure_complete = _is_structurally_complete(script)
    if not structure_complete:
        reasons.append("Script structure is incomplete for downstream pipeline stages.")
        fixes.append("Ensure title/logline/theme/locations plus balanced action/dialogue are present.")

    story_anchor = load_story_anchor(run_path, state)
    story_anchor_present = story_anchor is not None
    anchor_title_match = True
    character_consistency = 100.0
    script_faithfulness = 100.0

    retry_mode = state.current_iteration > 1
    title_lock_required = retry_mode and config.thresholds.require_title_lock_on_retry
    character_consistency_ok = True
    script_faithfulness_ok = True
    anchor_ready = True

    if retry_mode and not story_anchor_present:
        anchor_ready = False
        reasons.append("Story anchor is missing for retry continuity validation.")
        fixes.append("Restore iter-01 story_anchor.json or recreate the run with anchor bootstrap.")

    if story_anchor is not None:
        anchor_title_match = title_matches_anchor(story_anchor, script)
        character_consistency = character_consistency_pct(story_anchor, script)
        script_faithfulness = script_faithfulness_pct(story_anchor, script)

        character_consistency_ok = character_consistency >= config.thresholds.min_anchor_character_overlap_pct
        script_faithfulness_ok = script_faithfulness >= config.thresholds.min_anchor_fact_coverage_pct

        if title_lock_required and not anchor_title_match:
            reasons.append("Retry script changed title from story anchor.")
            fixes.append("Keep the anchor title unchanged; patch only gate-reported defects.")
        if retry_mode and not character_consistency_ok:
            reasons.append("Retry script drifted from anchor character set.")
            fixes.append("Restore anchor character roster and avoid replacing principal cast.")
        if retry_mode and not script_faithfulness_ok:
            reasons.append("Retry script no longer preserves enough anchor story beats.")
            fixes.append("Reinstate must-keep anchor beats while keeping fixes minimal.")

    narrative_coherence = _narrative_coherence_score(
        line_count=line_count,
        placeholder_lines=placeholder_lines,
        adjacent_character_violations=adjacent_character_violations,
        multi_action_lines=multi_action_lines,
        tight_spatial_transition_pairs=tight_spatial_transition_pairs,
        structure_complete=structure_complete,
    )
    narrative_coherence_ok = narrative_coherence >= config.thresholds.min_narrative_coherence_score
    if not narrative_coherence_ok:
        reasons.append("Narrative coherence score is below configured floor.")
        fixes.append("Simplify adjacent transitions and preserve a stable beat progression.")

    passed = (
        duration_ok
        and not undeclared_speakers
        and placeholder_lines == 0
        and line_count >= 10
        and adjacent_character_violations == 0
        and multi_action_lines == 0
        and complex_visual_without_closeup == 0
        and adjacent_same_background_pairs == 0
        and tight_spatial_transition_pairs == 0
        and fine_grained_visual_elements <= 2
        and concept_alignment_ok
        and structure_complete
        and narrative_coherence_ok
        and anchor_ready
        and (not title_lock_required or anchor_title_match)
        and (not retry_mode or character_consistency_ok)
        and (not retry_mode or script_faithfulness_ok)
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
            "adjacent_same_background_pairs": adjacent_same_background_pairs,
            "tight_spatial_transition_pairs": tight_spatial_transition_pairs,
            "fine_grained_visual_elements": fine_grained_visual_elements,
            "concept_alignment_pct": round(concept_alignment_pct, 2),
            "structure_complete": structure_complete,
            "story_anchor_present": story_anchor_present,
            "anchor_title_match": anchor_title_match,
            "character_consistency": round(character_consistency, 2),
            "script_faithfulness": round(script_faithfulness, 2),
            "narrative_coherence": round(narrative_coherence, 2),
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


def _count_adjacent_same_background_pairs(script: ScriptArtifact) -> int:
    keys = [_infer_background_key(line.text, script.locations) for line in script.lines]
    count = 0
    for prev, curr in zip(keys, keys[1:]):
        if prev and curr and prev == curr:
            count += 1
    return count


def _count_tight_spatial_transition_pairs(script: ScriptArtifact) -> int:
    count = 0
    spatial_tokens = (
        "door",
        "doorway",
        "corridor",
        "hallway",
        "stair",
        "elevator",
        "entrance",
        "exit",
    )
    movement_tokens = (
        "enter",
        "exit",
        "move",
        "walk",
        "step",
        "cross",
        "through",
        "toward",
        "towards",
        "from",
        "to",
    )

    for prev_line, curr_line in zip(script.lines, script.lines[1:]):
        prev_bg = _infer_background_key(prev_line.text, script.locations)
        curr_bg = _infer_background_key(curr_line.text, script.locations)
        if not prev_bg or not curr_bg or prev_bg == curr_bg:
            continue

        joined = f"{prev_line.text} {curr_line.text}".casefold()
        if any(token in joined for token in spatial_tokens) and any(token in joined for token in movement_tokens):
            count += 1
    return count


def _infer_background_key(text: str, locations: list[str]) -> str | None:
    lower = text.casefold()

    for location in sorted((item.casefold() for item in locations if item.strip()), key=len, reverse=True):
        if location in lower:
            return f"loc:{location}"

    fallback_keywords = (
        "mountain",
        "desert",
        "street",
        "dining table",
        "apartment",
        "desk",
        "void",
        "pod",
        "control room",
        "lab",
        "hospital",
        "corridor",
        "hallway",
        "beach",
        "forest",
    )
    for item in fallback_keywords:
        if item in lower:
            return f"kw:{item}"
    return None


def _has_fine_grained_visual_elements(text: str) -> bool:
    lower = text.casefold()
    tokens = (
        "small text",
        "tiny text",
        "code",
        "interface",
        "screen",
        "phone",
        "monitor",
        "label",
        "document",
        "photo",
        "mirror",
        "digits",
    )
    return any(token in lower for token in tokens)


def _concept_alignment_pct(core_concepts: list[str], script: ScriptArtifact) -> float:
    if not core_concepts:
        return 100.0
    haystack = " ".join([script.title, script.logline, script.theme, *(line.text for line in script.lines)]).casefold()
    hits = sum(1 for concept in core_concepts if concept.strip() and concept.casefold() in haystack)
    return (hits / len(core_concepts)) * 100.0


def _is_structurally_complete(script: ScriptArtifact) -> bool:
    has_header_fields = bool(script.title.strip() and script.logline.strip() and script.theme.strip())
    has_locations = len([item for item in script.locations if item.strip()]) >= 2
    has_actions = any(line.kind == "action" for line in script.lines)
    has_dialogue = any(line.kind == "dialogue" for line in script.lines)
    return has_header_fields and has_locations and has_actions and has_dialogue


def _narrative_coherence_score(
    *,
    line_count: int,
    placeholder_lines: int,
    adjacent_character_violations: int,
    multi_action_lines: int,
    tight_spatial_transition_pairs: int,
    structure_complete: bool,
) -> float:
    score = 100.0
    if line_count < 10:
        score -= 15.0
    if placeholder_lines:
        score -= min(25.0, placeholder_lines * 10.0)
    if adjacent_character_violations:
        score -= min(25.0, adjacent_character_violations * 3.0)
    if multi_action_lines:
        score -= min(25.0, multi_action_lines * 4.0)
    if tight_spatial_transition_pairs:
        score -= min(20.0, tight_spatial_transition_pairs * 5.0)
    if not structure_complete:
        score -= 20.0
    return max(0.0, min(100.0, score))
