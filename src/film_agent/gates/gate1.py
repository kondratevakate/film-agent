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
from film_agent.schemas.artifacts import GateReport, ScriptArtifact, StoryQAResult
from film_agent.gates.story_qa import _analyze_script
from film_agent.io.hashing import sha256_json
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
    duration_ok = config.duration_min_s <= estimated_duration_s <= config.duration_max_s
    if not duration_ok:
        reasons.append(
            f"Estimated script duration {estimated_duration_s:.2f}s is outside [{config.duration_min_s}, {config.duration_max_s}]."
        )
        fixes.append(
            f"Trim or extend script timing so estimated duration fits {config.duration_min_s}-{config.duration_max_s} seconds."
        )

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
    if line_count < 20:
        reasons.append("Script is too sparse for a rich visual story.")
        fixes.append("Provide at least 20 timed lines for diverse shot coverage.")

    # Compute metrics for warnings (non-blocking quality issues)
    adjacent_character_violations = _count_adjacent_primary_character_violations(script)
    multi_action_lines = sum(1 for line in script.lines if line.kind == "action" and _has_multiple_primary_actions(line.text))
    complex_visual_without_closeup = sum(1 for line in script.lines if _complex_visual_without_closeup(line.text))
    adjacent_same_background_pairs = _count_adjacent_same_background_pairs(script)
    tight_spatial_transition_pairs = _count_tight_spatial_transition_pairs(script)
    fine_grained_visual_elements = sum(1 for line in script.lines if _has_fine_grained_visual_elements(line.text))

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

    # =========================================================================
    # Story QA: 14 Storytelling Criteria (integrated from story_qa.py)
    # =========================================================================
    script_hash = sha256_json(script.model_dump(mode="json"))
    story_qa_result: StoryQAResult = _analyze_script(
        script, script_hash, state.current_iteration, config
    )

    # Check if story quality passes
    story_qa_score = story_qa_result.overall_score
    story_qa_passed = story_qa_result.passed  # overall >= 70 and no criterion below 40
    story_qa_threshold = getattr(config.thresholds, "min_story_qa_score", 60.0)

    if not story_qa_passed:
        reasons.append(f"Story QA failed: overall score {story_qa_score:.1f}/100.")
        for issue in story_qa_result.blocking_issues[:3]:
            reasons.append(f"  - {issue}")
        for rec in story_qa_result.recommendations[:3]:
            fixes.append(rec)

    # Separate blocking issues from warnings
    # Blocking: critical issues that prevent downstream processing
    # Warnings: quality issues that should be addressed but don't block progress
    warnings: list[str] = []

    # =========================================================================
    # MAViS-style checks: warnings or blocking depending on strict_mavis_mode
    # =========================================================================
    t = config.thresholds
    mavis_ok = True  # Becomes False if any MAViS check fails in strict mode

    if adjacent_character_violations > 0:
        warnings.append(f"Adjacent character violations: {adjacent_character_violations} (consider adding separator shots)")

    if multi_action_lines > 0:
        msg = f"Multi-action lines: {multi_action_lines} (consider splitting into separate lines)"
        warnings.append(msg)
        if t.strict_mavis_mode and multi_action_lines > t.max_multi_action_lines:
            reasons.append(f"MAViS: multi_action_lines ({multi_action_lines}) exceeds limit ({t.max_multi_action_lines}).")
            fixes.append("Split compound actions into separate script lines (one simple action per shot).")
            mavis_ok = False

    if complex_visual_without_closeup > 0:
        warnings.append(f"Complex visuals without close-up: {complex_visual_without_closeup} (consider adding close-up framing)")

    if adjacent_same_background_pairs > 0:
        msg = f"Adjacent same background pairs: {adjacent_same_background_pairs} (consider alternating backgrounds)"
        warnings.append(msg)
        if t.strict_mavis_mode and adjacent_same_background_pairs > t.max_adjacent_same_background:
            reasons.append(f"MAViS: adjacent_same_background ({adjacent_same_background_pairs}) exceeds limit.")
            fixes.append("Avoid consecutive scenes with identical backgrounds; add transition shots.")
            mavis_ok = False

    if tight_spatial_transition_pairs > 0:
        msg = f"Tight spatial transitions: {tight_spatial_transition_pairs} (consider looser transition shots)"
        warnings.append(msg)
        if t.strict_mavis_mode and tight_spatial_transition_pairs > t.max_tight_spatial_transitions:
            reasons.append(f"MAViS: tight_spatial_transitions ({tight_spatial_transition_pairs}) exceeds limit.")
            fixes.append("Add establishing or transition shots between tight spatial jumps.")
            mavis_ok = False

    if fine_grained_visual_elements > t.max_fine_grained_visual_elements:
        msg = f"Fine-grained visual elements: {fine_grained_visual_elements} (consider simplifying details)"
        warnings.append(msg)
        if t.strict_mavis_mode:
            reasons.append(f"MAViS: fine_grained_visual_elements ({fine_grained_visual_elements}) exceeds limit.")
            fixes.append("Replace fine-grained details (text, interfaces, small objects) with simpler descriptions.")
            mavis_ok = False

    # =========================================================================
    # Scene-to-scene coherence check
    # =========================================================================
    scene_coherence_score, scene_coherence_issues = _check_scene_coherence(script)
    scene_coherence_ok = scene_coherence_score >= t.min_scene_coherence_score

    if not scene_coherence_ok:
        reasons.append(f"Scene coherence score ({scene_coherence_score:.1f}) below threshold ({t.min_scene_coherence_score:.1f}).")
        for issue in scene_coherence_issues[:3]:
            fixes.append(f"Add transition: {issue}")

    # Blocking conditions only (critical for pipeline)
    passed = (
        duration_ok
        and not undeclared_speakers
        and placeholder_lines == 0
        and line_count >= 20
        and concept_alignment_ok
        and structure_complete
        and narrative_coherence_ok
        and anchor_ready
        and (not title_lock_required or anchor_title_match)
        and (not retry_mode or character_consistency_ok)
        and (not retry_mode or script_faithfulness_ok)
        and story_qa_passed  # 14 storytelling criteria must pass
        and mavis_ok  # MAViS checks in strict mode
        and scene_coherence_ok  # Scene-to-scene coherence
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
            "duration_min_s": config.duration_min_s,
            "duration_max_s": config.duration_max_s,
            "duration_target_s": config.duration_target_s,
            "warnings": warnings,  # Non-blocking quality issues
            "warning_count": len(warnings),
            # Story QA: 14 storytelling criteria
            "story_qa_passed": story_qa_passed,
            "story_qa_score": round(story_qa_score, 2),
            "story_qa_dramatic_question": round(story_qa_result.dramatic_question.clarity_score, 2),
            "story_qa_cause_effect": round(story_qa_result.cause_effect.score, 2),
            "story_qa_conflict": round(story_qa_result.conflict.score, 2),
            "story_qa_stakes": round(story_qa_result.stakes_escalation.score, 2),
            "story_qa_agency": round(story_qa_result.agency.score, 2),
            "story_qa_thematic": round(story_qa_result.thematic_consistency.score, 2),
            "story_qa_motifs": round(story_qa_result.motif_callback.score, 2),
            "story_qa_pacing": round(story_qa_result.pacing_texture.score, 2),
            "story_qa_finale": round(story_qa_result.causal_finale.score, 2),
            "story_qa_blocking_issues": story_qa_result.blocking_issues,
            # MAViS strict mode
            "strict_mavis_mode": t.strict_mavis_mode,
            "mavis_ok": mavis_ok,
            # Scene-to-scene coherence
            "scene_coherence_score": round(scene_coherence_score, 2),
            "scene_coherence_ok": scene_coherence_ok,
            "scene_coherence_issues": scene_coherence_issues[:3],
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
    if line_count < 20:
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


def _check_scene_coherence(script: ScriptArtifact) -> tuple[float, list[str]]:
    """Check for where/when/why contradictions between adjacent scenes.

    Detects location jumps without transition markers (e.g., "cafe" -> "home"
    without "cut to", "later", movement verbs, etc.).

    Returns:
        (score, list of coherence issues)
    """
    issues: list[str] = []
    locations = script.locations

    # Markers that indicate intentional transitions
    transition_markers = [
        "cut to", "later", "meanwhile", "next day", "hours later",
        "the next morning", "that evening", "fade to", "dissolve to",
        "moments later", "time passes", "flashback", "flash forward",
    ]

    # Markers that indicate character movement between locations
    movement_markers = [
        "walks to", "arrives at", "enters", "leaves", "exits",
        "goes to", "heads to", "steps into", "comes out of",
        "moves to", "travels to", "returns to", "drives to",
    ]

    # Track current location
    current_loc: str | None = None
    prev_loc: str | None = None

    for i, line in enumerate(script.lines):
        text_lower = line.text.casefold()

        # Detect location from line
        detected_loc = _infer_background_key(line.text, locations)

        if detected_loc and detected_loc != current_loc:
            prev_loc = current_loc
            current_loc = detected_loc

            # Check if location change has transition or movement
            has_transition = any(marker in text_lower for marker in transition_markers)
            has_movement = any(marker in text_lower for marker in movement_markers)

            # Also check previous line for transition markers
            if i > 0:
                prev_text = script.lines[i - 1].text.casefold()
                has_transition |= any(marker in prev_text for marker in transition_markers)
                has_movement |= any(marker in prev_text for marker in movement_markers)

            if prev_loc and not (has_transition or has_movement):
                # Location changed without explanation
                issues.append(f"L{i+1}: location jump '{prev_loc}' -> '{current_loc}' without transition")

    # Score: 100 - 15 per unexplained location jump
    score = max(0.0, 100.0 - len(issues) * 15.0)
    return score, issues
