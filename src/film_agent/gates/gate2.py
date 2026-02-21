"""Gate 2: script review / script doctor gate."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from film_agent.config import RunConfig
from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.schemas.artifacts import GateReport, ScriptArtifact, ScriptReviewArtifact
from film_agent.state_machine.state_store import RunStateData


def evaluate_gate2(run_path: Path, state: RunStateData, config: RunConfig) -> GateReport:
    reasons: list[str] = []
    fixes: list[str] = []

    script = load_artifact_for_agent(run_path, state, "showrunner")
    if script is None:
        reasons.append("Missing script artifact.")
        fixes.append("Submit script JSON before running Gate2.")
        return GateReport(
            gate="gate2",
            passed=False,
            iteration=state.current_iteration,
            metrics={
                "review_present": 0.0,
                "lock_story_facts": False,
                "character_registry_coverage_pct": 0.0,
                "unresolved_items": 999,
            },
            reasons=reasons,
            fix_instructions=fixes,
        )

    review = load_artifact_for_agent(run_path, state, "direction")
    if review is None:
        reasons.append("Missing script review artifact.")
        fixes.append("Submit ScriptReview JSON before running Gate2.")
        return GateReport(
            gate="gate2",
            passed=False,
            iteration=state.current_iteration,
            metrics={
                "review_present": 0.0,
                "lock_story_facts": False,
                "character_registry_coverage_pct": 0.0,
                "unresolved_items": 999,
            },
            reasons=reasons,
            fix_instructions=fixes,
        )

    script = cast(ScriptArtifact, script)
    review = cast(ScriptReviewArtifact, review)

    script_chars = {_normalize_character_entry(item) for item in script.characters if _normalize_character_entry(item)}
    reviewed_chars = {
        _normalize_character_entry(item) for item in review.approved_character_registry if _normalize_character_entry(item)
    }
    coverage_pct = (len(script_chars & reviewed_chars) / max(len(script_chars), 1)) * 100.0
    if coverage_pct < 100.0:
        reasons.append("Script review does not cover all declared script characters.")
        fixes.append("Update approved_character_registry to include every script character.")

    unresolved_items = sum(1 for item in review.unresolved_items if item.strip())
    if unresolved_items > 0:
        reasons.append("Script review still has unresolved continuity/story items.")
        fixes.append("Resolve unresolved_items before promotion.")

    todo_notes = sum(
        1
        for item in [*review.revision_notes, *review.unresolved_items]
        if "todo" in item.lower() or "tbd" in item.lower() or "??" in item
    )
    if todo_notes > 0:
        reasons.append("Script review contains TODO/TBD markers.")
        fixes.append("Replace temporary notes with explicit decisions.")

    if not review.lock_story_facts:
        reasons.append("lock_story_facts must be true before downstream prompt generation.")
        fixes.append("Set lock_story_facts=true only after final review pass.")

    if review.script_hash_hint and len(review.script_hash_hint.strip()) < 8:
        reasons.append("script_hash_hint is present but too short to be useful.")
        fixes.append("Use a stable hash/id reference for the approved script version.")

    # Character profile validation for visual consistency
    character_profile_score, character_profile_issues = _validate_character_profiles(script, review)
    character_profile_ok = character_profile_score >= config.thresholds.min_character_profile_score

    if not character_profile_ok:
        reasons.append(f"Character profiles incomplete ({character_profile_score:.0f}% < {config.thresholds.min_character_profile_score:.0f}%).")
        for issue in character_profile_issues[:3]:
            fixes.append(f"Add visual description: {issue}")

    passed = (
        coverage_pct == 100.0
        and unresolved_items == 0
        and todo_notes == 0
        and review.lock_story_facts
        and character_profile_ok
    )

    return GateReport(
        gate="gate2",
        passed=passed,
        iteration=state.current_iteration,
        metrics={
            "review_present": 100.0,
            "script_version": review.script_version,
            "lock_story_facts": review.lock_story_facts,
            "character_registry_coverage_pct": round(coverage_pct, 2),
            "approved_story_facts": len(review.approved_story_facts),
            "unresolved_items": unresolved_items,
            "todo_notes": todo_notes,
            "direction_pack_id": state.latest_direction_pack_id,
            "duration_target_s": config.duration_target_s,
            # Character profile validation for visual consistency
            "character_profile_score": round(character_profile_score, 2),
            "character_profile_ok": character_profile_ok,
            "character_profile_issues": character_profile_issues[:5],
        },
        reasons=_unique(reasons),
        fix_instructions=_unique(fixes),
    )


def _unique(items: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out


def _normalize_character_entry(raw: str) -> str:
    text = raw.strip()
    if not text:
        return ""
    # Allow entries like "Name: short description" from direction outputs.
    if ":" in text:
        text = text.split(":", 1)[0].strip()
    return " ".join(text.split())


def _validate_character_profiles(
    script: ScriptArtifact,
    review: ScriptReviewArtifact,
) -> tuple[float, list[str]]:
    """Validate character profiles are complete enough for visual generation.

    Checks that each character in the registry has:
    1. Appearance/physical description keywords
    2. Costume/wardrobe information

    Returns:
        (score, list of issues)
    """
    issues: list[str] = []

    appearance_markers = [
        "wearing", "dressed", "hair", "age", "build", "tall", "short",
        "young", "old", "eyes", "skin", "face", "outfit", "clothes",
        "costume", "uniform", "suit", "dress", "shirt", "pants", "shoes",
    ]

    for entry in review.approved_character_registry:
        if ":" not in entry:
            # No description at all
            name = entry.strip()
            issues.append(f"{name}: missing character description")
            continue

        name, desc = entry.split(":", 1)
        name = name.strip()
        desc_lower = desc.lower()

        has_appearance = any(marker in desc_lower for marker in appearance_markers)
        if not has_appearance:
            issues.append(f"{name}: missing appearance/costume description for visual consistency")

    # Score: 100 - 20 per missing profile
    score = max(0.0, 100.0 - len(issues) * 20.0)
    return score, issues
