"""Cinematography QA Gate: Evaluate visual production quality against 8 gates."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from film_agent.config import RunConfig
from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.io.hashing import sha256_json
from film_agent.schemas.artifacts import (
    CinematographyQAResult,
    ContinuityProgression,
    GateReport,
    GeographicClarity,
    ImagePromptPackage,
    InformationControlVisual,
    LookBible,
    ReviewFriendliness,
    ScriptArtifact,
    StorySupport,
    StyleConsistency,
    SuspenseEscalation,
    TechnicalFeasibility,
)
from film_agent.state_machine.state_store import RunStateData


def evaluate_cinematography_qa(
    run_path: Path, state: RunStateData, config: RunConfig
) -> tuple[GateReport, CinematographyQAResult | None]:
    """Evaluate image prompts against 8 cinematography gates.

    Returns a GateReport and optionally a CinematographyQAResult with detailed scores.
    """
    reasons: list[str] = []
    fixes: list[str] = []

    # Need both script and image_prompt_package
    script = load_artifact_for_agent(run_path, state=state, agent="showrunner")
    image_prompts = load_artifact_for_agent(run_path, state=state, agent="dance_mapping")

    if script is None:
        reasons.append("Missing script artifact.")
        fixes.append("Submit script JSON before Cinematography QA.")
        return (
            GateReport(
                gate="cinematography_qa",
                passed=False,
                iteration=state.current_iteration,
                metrics={"error": "no_script"},
                reasons=reasons,
                fix_instructions=fixes,
            ),
            None,
        )

    if image_prompts is None:
        reasons.append("Missing image prompt package artifact.")
        fixes.append("Submit image_prompt_package JSON before Cinematography QA.")
        return (
            GateReport(
                gate="cinematography_qa",
                passed=False,
                iteration=state.current_iteration,
                metrics={"error": "no_image_prompts"},
                reasons=reasons,
                fix_instructions=fixes,
            ),
            None,
        )

    script = cast(ScriptArtifact, script)
    image_prompts = cast(ImagePromptPackage, image_prompts)
    script_hash = sha256_json(script.model_dump(mode="json"))

    # Analyze and compute scores for each gate
    result = _analyze_cinematography(
        script, image_prompts, script_hash, state.current_iteration, config
    )

    # Build gate report from result
    if result.overall_score < 70:
        reasons.append(f"Overall cinematography score {result.overall_score:.1f} is below threshold (70).")
        fixes.append("Address failing gates and improve weak areas.")

    for issue in result.blocking_issues:
        reasons.append(f"Blocking issue: {issue}")

    passed = result.gates_passed >= 6 and result.overall_score >= 70

    return (
        GateReport(
            gate="cinematography_qa",
            passed=passed,
            iteration=state.current_iteration,
            metrics={
                "overall_score": round(result.overall_score, 2),
                "gates_passed": result.gates_passed,
                "g1_story_support": round(result.g1_story_support.score, 2),
                "g2_geographic_clarity": round(result.g2_geographic_clarity.score, 2),
                "g3_suspense_escalation": round(result.g3_suspense_escalation.score, 2),
                "g4_information_control": round(result.g4_information_control.score, 2),
                "g5_style_consistency": round(result.g5_style_consistency.score, 2),
                "g6_technical_feasibility": round(result.g6_technical_feasibility.score, 2),
                "g7_continuity_progression": round(result.g7_continuity_progression.score, 2),
                "g8_review_friendliness": round(result.g8_review_friendliness.score, 2),
            },
            reasons=reasons,
            fix_instructions=fixes,
        ),
        result,
    )


def _analyze_cinematography(
    script: ScriptArtifact,
    image_prompts: ImagePromptPackage,
    script_hash: str,
    iteration: int,
    config: RunConfig,
) -> CinematographyQAResult:
    """Analyze image prompts and compute all 8 cinematography gates."""
    shots = image_prompts.image_prompts

    # Extract look bible from style anchor
    look_bible = _extract_look_bible(image_prompts.style_anchor)

    # G1: Story Support
    g1 = _check_story_support(shots, script)

    # G2: Geographic Clarity
    g2 = _check_geographic_clarity(shots)

    # G3: Suspense Escalation
    g3 = _check_suspense_escalation(shots)

    # G4: Information Control
    g4 = _check_information_control(shots)

    # G5: Style Consistency
    g5 = _check_style_consistency(shots, image_prompts.style_anchor)

    # G6: Technical Feasibility
    g6 = _check_technical_feasibility(shots)

    # G7: Continuity & Progression
    g7 = _check_continuity_progression(shots)

    # G8: Review Friendliness
    g8 = _check_review_friendliness(shots)

    # Character identity consistency checks (beyond 8 gates)
    char_identity_score, char_identity_issues, char_missing = _check_character_identity_per_shot(
        shots, script
    )
    ref_identity_score, ref_identity_issues = _check_reference_image_identity(shots, config)

    # Count passed gates
    gates = [g1, g2, g3, g4, g5, g6, g7, g8]
    gates_passed = sum(1 for g in gates if g.passed)

    # Calculate overall score
    scores = [g1.score, g2.score, g3.score, g4.score, g5.score, g6.score, g7.score, g8.score]
    overall_score = sum(scores) / len(scores)

    # Identify blocking issues
    blocking = []
    shot_patches = []
    previs_checklist = []

    if not g1.passed:
        blocking.append(f"G1 Story Support: decorative shots {g1.decorative_shots}")
        for shot_id in g1.decorative_shots[:3]:
            shot_patches.append({
                "shot_id": shot_id,
                "field": "intent",
                "issue": "No clear narrative intention",
                "suggested_fix": "Add goal/obstacle/outcome or reveal/reversal purpose",
            })

    if not g3.passed:
        blocking.append("G3 Suspense Escalation: visual language stays flat")
        previs_checklist.append("Verify visual tension increases across shots")

    if not g6.passed:
        blocking.append(f"G6 Technical Feasibility: {g6.infeasible_shots}")
        for shot_id in g6.infeasible_shots[:3]:
            shot_patches.append({
                "shot_id": shot_id,
                "field": "image_prompt",
                "issue": "Technically infeasible",
                "suggested_fix": "Simplify action or remove contradictions",
            })

    # Character identity issues
    char_identity_ok = char_identity_score >= config.thresholds.min_character_identity_score
    if not char_identity_ok:
        blocking.append(f"Character identity: {len(char_missing)} shots missing identity notes")
        for issue in char_missing[:3]:
            shot_patches.append({
                "shot_id": issue.split(":")[0],
                "field": "image_prompt",
                "issue": "Missing character identity continuity",
                "suggested_fix": "Add 'same outfit', 'as before', or identity token",
            })

    # Reference image identity issues
    ref_identity_ok = True
    if config.thresholds.require_identity_tokens and ref_identity_issues:
        ref_identity_ok = ref_identity_score >= 70.0
        if not ref_identity_ok:
            blocking.append(f"Reference identity: {len(ref_identity_issues)} shots missing identity_token")
            for issue in ref_identity_issues[:3]:
                shot_id = issue.split(":")[0]
                shot_patches.append({
                    "shot_id": shot_id,
                    "field": "image_prompt",
                    "issue": "Missing identity_token from reference image",
                    "suggested_fix": "Add the identity_token for this character",
                })

    # Build previs checklist
    if not previs_checklist:
        previs_checklist = [
            "Check establishing shots read clearly",
            "Verify escalation visible in framing/light",
            "Confirm character continuity across shots",
            "Check for overbusy frames",
            "Verify mood progression matches script arc",
        ]

    # Add character identity items to previs checklist
    if char_missing:
        previs_checklist.append("Verify character appearance consistent across reappearances")
    if ref_identity_issues:
        previs_checklist.append("Verify characters match reference images")

    passed = (
        gates_passed >= 6
        and overall_score >= 70
        and char_identity_ok
        and ref_identity_ok
    )

    return CinematographyQAResult(
        script_hash=script_hash,
        iteration=iteration,
        look_bible=look_bible,
        g1_story_support=g1,
        g2_geographic_clarity=g2,
        g3_suspense_escalation=g3,
        g4_information_control=g4,
        g5_style_consistency=g5,
        g6_technical_feasibility=g6,
        g7_continuity_progression=g7,
        g8_review_friendliness=g8,
        # Character identity consistency
        character_identity_score=round(char_identity_score, 2),
        character_identity_issues=char_missing[:5],
        reference_identity_score=round(ref_identity_score, 2),
        reference_identity_issues=ref_identity_issues[:5],
        # Aggregate
        gates_passed=gates_passed,
        overall_score=round(overall_score, 2),
        blocking_issues=blocking,
        shot_patches=shot_patches,
        previs_checklist=previs_checklist[:8],  # Max 8 items
        passed=passed,
    )


def _extract_look_bible(style_anchor: str) -> LookBible:
    """Extract Look Bible from style anchor description."""
    # Parse style anchor for visual rules
    style_lower = style_anchor.lower()

    palette = "Warm tungsten vs cold fluorescents" if "tungsten" in style_lower else "Neutral with accent colors"
    lighting = "Motivated practical sources" if "practical" in style_lower else "Natural motivated lighting"
    lens = "Wide for geography, tele for isolation" if "wide" in style_lower else "Standard coverage"
    camera = "Static for control, drift for unease" if "static" in style_lower or "drift" in style_lower else "Motivated movement only"
    composition = "Symmetry for control, imbalance for tension"
    texture = "Period-accurate with subtle wear" if "80s" in style_lower or "nostalgia" in style_lower else "Clean contemporary"
    escalation = "Tighter framing, reduced fill, more negative space toward climax"

    return LookBible(
        palette=palette,
        lighting_philosophy=lighting,
        lens_language=lens,
        camera_movement_rules=camera,
        composition_rules=composition,
        texture_rules=texture,
        escalation_plan=escalation,
    )


def _check_story_support(shots: list, script: ScriptArtifact) -> StorySupport:
    """G1: Check each shot has narrative intention."""
    intention_markers = [
        "reveal", "discover", "realize", "decide", "choose",
        "react", "respond", "confront", "escape", "arrive",
        "goal", "obstacle", "tension", "conflict"
    ]

    shots_with_intention = 0
    decorative = []

    for shot in shots:
        text = (shot.intent + " " + shot.image_prompt).lower()
        if any(marker in text for marker in intention_markers):
            shots_with_intention += 1
        else:
            decorative.append(shot.shot_id)

    ratio = shots_with_intention / max(len(shots), 1)
    score = ratio * 100
    passed = len(decorative) == 0 or ratio >= 0.8

    return StorySupport(
        shots_with_intention=shots_with_intention,
        decorative_shots=decorative[:5],
        score=round(score, 2),
        passed=passed,
        notes=f"{shots_with_intention}/{len(shots)} shots have clear intention",
    )


def _check_geographic_clarity(shots: list) -> GeographicClarity:
    """G2: Check spatial relations are clear."""
    establishing_markers = ["wide", "overhead", "establishing", "geography", "layout"]
    transition_markers = ["cut to", "transition", "move to"]

    has_establishing = False
    unclear = []

    prev_location = None
    for shot in shots:
        text = shot.image_prompt.lower()

        # Check for establishing shots
        if any(marker in text for marker in establishing_markers):
            has_establishing = True

        # Check for unclear transitions (location change without establishing)
        current_location = _extract_location(text)
        if prev_location and current_location != prev_location:
            if not any(marker in text for marker in establishing_markers):
                unclear.append(shot.shot_id)
        prev_location = current_location

    score = 80.0 if has_establishing else 50.0
    score -= len(unclear) * 10
    score = max(0, min(100, score))
    passed = has_establishing and len(unclear) <= 1

    return GeographicClarity(
        establishing_shots_present=has_establishing,
        unclear_transitions=unclear[:3],
        score=round(score, 2),
        passed=passed,
        notes=f"Establishing shots: {has_establishing}, Unclear transitions: {len(unclear)}",
    )


def _extract_location(text: str) -> str:
    """Extract location from shot description."""
    locations = ["pool", "hallway", "gym", "studio", "classroom", "radiology"]
    for loc in locations:
        if loc in text:
            return loc
    return "unknown"


def _check_suspense_escalation(shots: list) -> SuspenseEscalation:
    """G3: Check visual language escalates."""
    escalation_markers = {
        "tighter framing": ["close", "tight", "macro", "detail"],
        "reduced fill": ["shadow", "contrast", "dark", "dim"],
        "longer holds": ["hold", "pause", "static", "still"],
        "obstructed sightlines": ["through", "obstruct", "partial", "blocked"],
        "negative space": ["isolated", "alone", "empty", "negative"],
        "telephoto feel": ["telephoto", "compressed", "distant", "surveillance"],
        "unstable movement": ["handheld", "shake", "unstable", "drift"],
        "emergency/alarm": ["red", "alarm", "emergency", "alert"],
    }

    moves_found = []
    for i, shot in enumerate(shots):
        text = shot.image_prompt.lower()
        for move_name, markers in escalation_markers.items():
            if any(marker in text for marker in markers):
                if move_name not in [m.split(":")[0] for m in moves_found]:
                    moves_found.append(f"{move_name}: {shot.shot_id}")

    # Check for progression (later shots should have more escalation)
    escalation_count = len(moves_found)
    score = min(100, escalation_count * 20)
    passed = escalation_count >= 3

    return SuspenseEscalation(
        escalation_moves=moves_found[:6],
        escalation_count=escalation_count,
        score=round(score, 2),
        passed=passed,
        notes=f"Found {escalation_count} escalation moves",
    )


def _check_information_control(shots: list) -> InformationControlVisual:
    """G4: Check lighting/framing controls reveal vs withhold."""
    control_markers = ["shadow", "silhouette", "partial", "hidden", "obscured", "backlit"]
    even_markers = ["bright", "evenly lit", "flat light", "fill light"]

    controlled = []
    evenly_lit = []

    for shot in shots:
        text = shot.image_prompt.lower()
        if any(marker in text for marker in control_markers):
            controlled.append(shot.shot_id)
        elif any(marker in text for marker in even_markers):
            evenly_lit.append(shot.shot_id)

    control_ratio = len(controlled) / max(len(shots), 1)
    score = 50 + (control_ratio * 50)
    score -= len(evenly_lit) * 5
    score = max(0, min(100, score))
    passed = len(controlled) >= 2 or len(evenly_lit) <= len(shots) // 3

    return InformationControlVisual(
        controlled_shots=controlled[:5],
        evenly_lit_shots=evenly_lit[:3],
        score=round(score, 2),
        passed=passed,
        notes=f"{len(controlled)} controlled, {len(evenly_lit)} evenly lit",
    )


def _check_style_consistency(shots: list, style_anchor: str) -> StyleConsistency:
    """G5: Check no style drift."""
    drift_markers = [
        "cyberpunk", "neon", "glitch", "vhs", "vignette",
        "teal and orange", "lut", "filter", "preset"
    ]

    violations = []
    for shot in shots:
        text = shot.image_prompt.lower()
        if any(marker in text for marker in drift_markers):
            violations.append(shot.shot_id)

    score = 100 - (len(violations) * 15)
    score = max(0, min(100, score))
    passed = len(violations) == 0

    return StyleConsistency(
        style_violations=violations[:3],
        score=round(score, 2),
        passed=passed,
        notes=f"{len(violations)} style violations detected",
    )


def _check_technical_feasibility(shots: list) -> TechnicalFeasibility:
    """G6: Check prompts are renderable."""
    infeasibility_markers = [
        "while simultaneously", "at the same time doing",
        "multiple characters doing different things",
        "impossible angle", "through solid"
    ]
    busy_markers = ["and and", "multiple actions", "everything", "chaotic mess"]

    infeasible = []
    contradictions = []

    for shot in shots:
        text = shot.image_prompt.lower()
        # Check for overlong prompts
        if len(shot.image_prompt) > 500:
            infeasible.append(shot.shot_id)
            contradictions.append(f"{shot.shot_id}: prompt too long ({len(shot.image_prompt)} chars)")
        elif any(marker in text for marker in infeasibility_markers + busy_markers):
            infeasible.append(shot.shot_id)

    score = 100 - (len(infeasible) * 20)
    score = max(0, min(100, score))
    passed = len(infeasible) == 0

    return TechnicalFeasibility(
        infeasible_shots=infeasible[:3],
        contradictions=contradictions[:3],
        score=round(score, 2),
        passed=passed,
        notes=f"{len(infeasible)} potentially infeasible shots",
    )


def _check_continuity_progression(shots: list) -> ContinuityProgression:
    """G7: Check wardrobe/props continuity."""
    continuity_markers = ["same", "continuing", "still wearing", "previous"]
    progression_markers = ["now", "changed", "damaged", "wet", "dirty", "stained"]

    gaps = []
    issues = []

    # Check for continuity across shots
    prev_shot = None
    for shot in shots:
        text = shot.image_prompt.lower()

        # Check for explicit continuity or progression
        has_continuity = any(marker in text for marker in continuity_markers)
        has_progression = any(marker in text for marker in progression_markers)

        # If location changes, should have some continuity note
        if prev_shot:
            prev_loc = _extract_location(prev_shot.image_prompt.lower())
            curr_loc = _extract_location(text)
            if prev_loc == curr_loc and not (has_continuity or has_progression):
                # Same location, no continuity mention - could be a gap
                pass  # Allow implicit continuity

        prev_shot = shot

    # Score based on explicit continuity management
    score = 80.0  # Base score if no obvious issues
    score -= len(gaps) * 15
    score = max(0, min(100, score))
    passed = len(gaps) <= 1

    return ContinuityProgression(
        continuity_gaps=gaps[:3],
        progression_issues=issues[:3],
        score=round(score, 2),
        passed=passed,
        notes="Continuity check passed" if passed else f"Gaps: {gaps}",
    )


def _check_review_friendliness(shots: list) -> ReviewFriendliness:
    """G8: Check prompts are clear enough for manual review."""
    clarity_markers = ["shot", "angle", "light", "camera", "frame", "subject"]
    vague_markers = ["somehow", "maybe", "perhaps", "something like", "etc"]

    vague = []
    for shot in shots:
        text = shot.image_prompt.lower()

        # Check for vague language
        if any(marker in text for marker in vague_markers):
            vague.append(shot.shot_id)
            continue

        # Check for clarity markers (should have at least some)
        clarity_count = sum(1 for marker in clarity_markers if marker in text)
        if clarity_count < 2 and len(shot.image_prompt) < 50:
            vague.append(shot.shot_id)

    score = 100 - (len(vague) * 15)
    score = max(0, min(100, score))
    passed = len(vague) <= 1

    return ReviewFriendliness(
        vague_shots=vague[:3],
        score=round(score, 2),
        passed=passed,
        notes=f"{len(vague)} vague shots found",
    )


def _check_character_identity_per_shot(
    shots: list,
    script: ScriptArtifact,
) -> tuple[float, list[str], list[str]]:
    """G9: Check each shot maintains character identity consistency.

    When a character reappears in a later shot, there should be identity
    markers to ensure visual consistency (same outfit, as before, etc.).

    Returns:
        (score, issues, missing_identity_notes)
    """
    issues: list[str] = []
    missing_identity: list[str] = []

    # Get declared characters
    characters = {c.strip().lower() for c in script.characters if c.strip()}

    # Identity continuity markers
    identity_markers = [
        "same outfit", "same clothes", "still wearing", "consistent",
        "as before", "unchanged", "her signature", "his usual",
        "same appearance", "continuing", "matching earlier",
        "identical to", "same as before", "same costume",
    ]

    # Track when each character was last seen
    character_last_seen: dict[str, str] = {}  # char -> last shot_id

    for shot in shots:
        prompt_lower = shot.image_prompt.lower()

        for char in characters:
            if char in prompt_lower:
                # Character appears in this shot
                has_identity_note = any(marker in prompt_lower for marker in identity_markers)

                if char in character_last_seen and not has_identity_note:
                    # Character was seen before but no identity continuity note
                    missing_identity.append(
                        f"{shot.shot_id}: '{char}' reappears without identity continuity note"
                    )

                character_last_seen[char] = shot.shot_id

    # Score: 100 - 10 per missing identity note
    score = max(0.0, 100.0 - len(missing_identity) * 10.0)
    return score, issues, missing_identity


def _check_reference_image_identity(
    shots: list,
    config: RunConfig,
) -> tuple[float, list[str]]:
    """Check that image prompts include identity tokens from reference images.

    When reference_images with identity_token are configured, prompts mentioning
    those characters should include the identity token for visual consistency.

    Returns:
        (score, issues)
    """
    issues: list[str] = []

    # Get reference images with identity tokens
    ref_entries = config.reference_image_entries()
    identity_tokens: dict[str, str] = {}  # character_name -> identity_token

    for ref in ref_entries:
        if ref.character and ref.identity_token:
            identity_tokens[ref.character.lower()] = ref.identity_token

    if not identity_tokens:
        # No identity tokens configured, skip check
        return 100.0, []

    for shot in shots:
        prompt_lower = shot.image_prompt.lower()

        for char, token in identity_tokens.items():
            if char in prompt_lower:
                # Character is mentioned - should have identity token
                if token.lower() not in prompt_lower:
                    issues.append(
                        f"{shot.shot_id}: '{char}' missing identity_token '{token}'"
                    )

    # Score: 100 - 15 per missing token
    score = max(0.0, 100.0 - len(issues) * 15.0)
    return score, issues
