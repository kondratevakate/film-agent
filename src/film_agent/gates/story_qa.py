"""Story QA Gate: Evaluate script against 14 professional storytelling criteria."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from film_agent.config import RunConfig
from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.io.hashing import sha256_json
from film_agent.schemas.artifacts import (
    AgencyCheck,
    CauseEffectCheck,
    CausalFinaleCheck,
    ConflictCheck,
    DialogQualityCheck,
    DramaticQuestionCheck,
    EconomyFocusCheck,
    GateReport,
    InformationControlCheck,
    MotifCallbackCheck,
    PacingTextureCheck,
    PromisePayoffCheck,
    ScriptArtifact,
    StakesEscalationCheck,
    StoryQAResult,
    SurpriseBalanceCheck,
    ThematicConsistencyCheck,
)
from film_agent.state_machine.state_store import RunStateData


def evaluate_story_qa(
    run_path: Path, state: RunStateData, config: RunConfig
) -> tuple[GateReport, StoryQAResult | None]:
    """Evaluate script against 14 storytelling criteria.

    Returns a GateReport and optionally a StoryQAResult with detailed scores.
    """
    reasons: list[str] = []
    fixes: list[str] = []

    script = load_artifact_for_agent(run_path, state=state, agent="showrunner")
    if script is None:
        reasons.append("Missing script artifact.")
        fixes.append("Submit script JSON before Story QA validation.")
        return (
            GateReport(
                gate="story_qa",
                passed=False,
                iteration=state.current_iteration,
                metrics={"error": "no_script"},
                reasons=reasons,
                fix_instructions=fixes,
            ),
            None,
        )

    script = cast(ScriptArtifact, script)
    script_hash = sha256_json(script.model_dump(mode="json"))

    # Analyze script and compute scores for each criterion
    result = _analyze_script(script, script_hash, state.current_iteration, config)

    # Build gate report from result
    if result.overall_score < 70:
        reasons.append(f"Overall story quality score {result.overall_score:.1f} is below threshold (70).")
        fixes.append("Address blocking issues and improve weak criteria.")

    for issue in result.blocking_issues:
        reasons.append(f"Blocking issue: {issue}")

    # Check for any criterion below minimum threshold (configurable, default 40)
    min_criterion = getattr(config.thresholds, "min_story_qa_criterion_score", 40.0)
    criteria_scores = [
        ("dramatic_question", result.dramatic_question.clarity_score),
        ("cause_effect", result.cause_effect.score),
        ("conflict", result.conflict.score),
        ("stakes_escalation", result.stakes_escalation.score),
        ("information_control", result.information_control.score),
        ("agency", result.agency.score),
        ("thematic_consistency", result.thematic_consistency.score),
        ("motif_callback", result.motif_callback.score),
        ("surprise_balance", result.surprise_balance.balance_score),
        ("promise_payoff", result.promise_payoff.score),
        ("pacing_texture", result.pacing_texture.score),
        ("dialog_quality", result.dialog_quality.score),
        ("economy_focus", result.economy_focus.score),
        ("causal_finale", result.causal_finale.score),
    ]

    for name, score in criteria_scores:
        if score < min_criterion:
            reasons.append(f"Criterion '{name}' score {score:.1f} is below threshold ({min_criterion:.0f}).")
            fixes.append(f"Prioritize fixing '{name}' before other improvements.")

    passed = result.overall_score >= 70 and all(score >= min_criterion for _, score in criteria_scores)

    return (
        GateReport(
            gate="story_qa",
            passed=passed,
            iteration=state.current_iteration,
            metrics={
                "overall_score": round(result.overall_score, 2),
                "dramatic_question": round(result.dramatic_question.clarity_score, 2),
                "cause_effect": round(result.cause_effect.score, 2),
                "conflict": round(result.conflict.score, 2),
                "stakes_escalation": round(result.stakes_escalation.score, 2),
                "information_control": round(result.information_control.score, 2),
                "agency": round(result.agency.score, 2),
                "thematic_consistency": round(result.thematic_consistency.score, 2),
                "motif_callback": round(result.motif_callback.score, 2),
                "surprise_balance": round(result.surprise_balance.balance_score, 2),
                "promise_payoff": round(result.promise_payoff.score, 2),
                "pacing_texture": round(result.pacing_texture.score, 2),
                "dialog_quality": round(result.dialog_quality.score, 2),
                "economy_focus": round(result.economy_focus.score, 2),
                "causal_finale": round(result.causal_finale.score, 2),
                "blocking_issues_count": len(result.blocking_issues),
            },
            reasons=reasons,
            fix_instructions=fixes + result.recommendations,
        ),
        result,
    )


def _analyze_script(
    script: ScriptArtifact,
    script_hash: str,
    iteration: int,
    config: RunConfig,
) -> StoryQAResult:
    """Analyze script and compute all 14 storytelling criteria scores.

    This is a rule-based heuristic analysis. For production use,
    this should be augmented with LLM-based evaluation.
    """
    lines = script.lines
    locations = script.locations
    dialogue_lines = [line for line in lines if line.kind == "dialogue"]

    # 1. Dramatic Question
    dramatic_q = _check_dramatic_question(script)

    # 2. Cause-Effect Chain
    cause_effect = _check_cause_effect(lines)

    # 3. Conflict per Scene
    conflict = _check_conflict(lines, locations)

    # 4. Stakes Escalation
    stakes = _check_stakes_escalation(lines)

    # 5. Information Control
    info_control = _check_information_control(lines, script)

    # 6. Agency
    agency = _check_agency(lines)

    # 7. Thematic Consistency
    thematic = _check_thematic_consistency(script)

    # 8. Motifs & Callbacks
    motifs = _check_motifs(lines)

    # 9. Surprise Balance
    surprise = _check_surprise_balance(lines)

    # 10. Promise & Payoff
    promise = _check_promise_payoff(script, lines)

    # 11. Pacing & Texture
    pacing = _check_pacing(lines)

    # 12. Dialog Quality
    dialog = _check_dialog_quality(dialogue_lines, script.characters)

    # 13. Economy & Focus
    economy = _check_economy(lines)

    # 14. Causal Finale
    finale = _check_causal_finale(lines)

    # Calculate overall score (equal weights)
    scores = [
        dramatic_q.clarity_score,
        cause_effect.score,
        conflict.score,
        stakes.score,
        info_control.score,
        agency.score,
        thematic.score,
        motifs.score,
        surprise.balance_score,
        promise.score,
        pacing.score,
        dialog.score,
        economy.score,
        finale.score,
    ]
    overall_score = sum(scores) / len(scores)

    # Identify blocking issues (configurable threshold, default 50)
    blocking_threshold = getattr(config.thresholds, "min_story_qa_criterion_score", 40.0)
    blocking = []
    recommendations = []

    if dramatic_q.clarity_score < blocking_threshold:
        blocking.append("dramatic_question: unclear what viewer is waiting for")
        recommendations.append("Add clear stakes/question by line 5-6")

    if cause_effect.score < blocking_threshold:
        blocking.append(f"cause_effect: chain breaks at {cause_effect.breaks}")
        recommendations.append("Ensure each scene forces the next (not just follows)")

    if conflict.score < blocking_threshold:
        blocking.append(f"conflict: missing in {conflict.scenes_missing_conflict}")
        recommendations.append("Add obstacle/opposition in each location")

    if agency.score < blocking_threshold:
        blocking.append("agency: hero decisions don't drive plot")
        recommendations.append("Add moment where protagonist CHOOSES despite cost")

    if finale.score < blocking_threshold:
        blocking.append("causal_finale: ending feels arbitrary")
        recommendations.append("Ensure finale results from earlier setup")

    passed = overall_score >= 70 and len(blocking) == 0

    return StoryQAResult(
        script_hash=script_hash,
        iteration=iteration,
        dramatic_question=dramatic_q,
        cause_effect=cause_effect,
        conflict=conflict,
        stakes_escalation=stakes,
        information_control=info_control,
        agency=agency,
        thematic_consistency=thematic,
        motif_callback=motifs,
        surprise_balance=surprise,
        promise_payoff=promise,
        pacing_texture=pacing,
        dialog_quality=dialog,
        economy_focus=economy,
        causal_finale=finale,
        overall_score=round(overall_score, 2),
        blocking_issues=blocking,
        recommendations=recommendations,
        passed=passed,
    )


# =============================================================================
# Individual Criterion Checks (Heuristic-based)
# =============================================================================


def _check_dramatic_question(script: ScriptArtifact) -> DramaticQuestionCheck:
    """Check if there's a clear dramatic question."""
    logline = script.logline.lower()
    theme = script.theme.lower()

    # Look for question-like patterns
    question_markers = ["will", "can", "does", "what if", "whether", "how"]
    has_question = any(marker in logline for marker in question_markers)

    # Check if logline implies stakes/goal
    stake_markers = ["must", "need", "survive", "escape", "discover", "reveal", "find", "save"]
    has_stakes = any(marker in logline for marker in stake_markers)

    if has_question and has_stakes:
        score = 85.0
        question_text = script.logline
    elif has_stakes:
        score = 70.0
        question_text = f"Implicit: {script.logline}"
    elif has_question:
        score = 60.0
        question_text = script.logline
    else:
        score = 40.0
        question_text = ""

    return DramaticQuestionCheck(
        present=score >= 60,
        question_text=question_text,
        clarity_score=score,
        notes="Heuristic analysis of logline and theme",
    )


def _check_cause_effect(lines: list) -> CauseEffectCheck:
    """Check cause-effect chain integrity."""
    # Heuristic: look for causal language and scene transitions
    causal_markers = ["because", "therefore", "so", "then", "after", "leads to", "causes"]
    transition_markers = ["cut to", "meanwhile", "later", "suddenly"]

    breaks = []
    total_transitions = 0

    for i, line in enumerate(lines[1:], start=1):
        text = line.text.lower()
        prev_text = lines[i - 1].text.lower()

        # Check for abrupt scene changes without causal connection
        if any(marker in text for marker in transition_markers):
            total_transitions += 1
            # If no causal marker in current or previous line, potential break
            if not any(marker in text + prev_text for marker in causal_markers):
                # Only flag if it seems like a location change
                if "cut to" in text:
                    breaks.append(line.line_id)

    # Score based on breaks vs total lines
    break_ratio = len(breaks) / max(len(lines), 1)
    score = max(0, 100 - (break_ratio * 200))

    return CauseEffectCheck(
        chain_intact=len(breaks) == 0,
        breaks=breaks[:5],  # Limit to first 5
        score=round(score, 2),
        notes=f"Found {len(breaks)} potential chain breaks",
    )


def _check_conflict(lines: list, locations: list[str]) -> ConflictCheck:
    """Check for conflict in each scene/location."""
    conflict_markers = [
        "against", "despite", "struggle", "fight", "resist", "refuse",
        "block", "stop", "prevent", "challenge", "confront", "oppose",
        "tension", "alarm", "panic", "angry", "hostile"
    ]

    location_conflicts: dict[str, bool] = {loc: False for loc in locations}
    scenes_with_conflict = 0

    for line in lines:
        text = line.text.lower()
        if any(marker in text for marker in conflict_markers):
            scenes_with_conflict += 1
            # Try to associate with location
            for loc in locations:
                if loc.lower() in text:
                    location_conflicts[loc] = True

    missing = [loc for loc, has_conflict in location_conflicts.items() if not has_conflict]

    # Score based on conflict ratio
    conflict_ratio = scenes_with_conflict / max(len(lines), 1)
    location_coverage = (len(locations) - len(missing)) / max(len(locations), 1)
    score = (conflict_ratio * 50 + location_coverage * 50)

    return ConflictCheck(
        scenes_with_conflict=scenes_with_conflict,
        scenes_missing_conflict=missing,
        score=round(min(100, score * 1.5), 2),  # Scale up
        notes=f"{scenes_with_conflict} lines with conflict markers",
    )


def _check_stakes_escalation(lines: list) -> StakesEscalationCheck:
    """Check for escalating stakes."""
    # Define stake levels
    stake_levels = {
        "curiosity": ["look", "notice", "see", "wonder"],
        "confusion": ["confused", "lost", "strange", "weird"],
        "discomfort": ["uncomfortable", "uneasy", "tense"],
        "threat": ["alarm", "emergency", "danger", "warning", "red"],
        "action": ["remove", "extract", "escape", "flee", "run"],
        "resolution": ["calm", "relief", "done", "safe", "okay"],
    }

    progression = []
    current_level = 0
    escalating = True

    for line in lines:
        text = line.text.lower()
        for i, (level, markers) in enumerate(stake_levels.items()):
            if any(marker in text for marker in markers):
                if level not in progression:
                    progression.append(level)
                if i < current_level:
                    escalating = False  # Stakes dropped
                current_level = max(current_level, i)

    score = min(100, len(progression) * 20) if escalating else max(40, len(progression) * 15)

    return StakesEscalationCheck(
        escalation_detected=escalating and len(progression) >= 3,
        progression=progression,
        score=round(score, 2),
        notes="Heuristic stake level detection",
    )


def _check_information_control(lines: list, script: ScriptArtifact) -> InformationControlCheck:
    """Check for information control techniques."""
    reveal_markers = ["realize", "discover", "reveal", "truth", "actually", "really"]
    irony_markers = ["doesn't know", "unaware", "hidden", "secret"]
    mystery_markers = ["mystery", "question", "who", "why", "what"]

    reveals = []
    technique = "none"

    for line in lines:
        text = line.text.lower()
        if any(marker in text for marker in reveal_markers):
            reveals.append(line.line_id)
            technique = "reframe"
        elif any(marker in text for marker in irony_markers):
            technique = "dramatic_irony"
        elif any(marker in text for marker in mystery_markers):
            technique = "mystery"

    # Check logline/theme for setup
    if "trace" in script.logline.lower() or "contrast" in script.theme.lower():
        technique = "reframe" if reveals else "mystery"
        score = 75.0
    else:
        score = 60.0 if technique != "none" else 40.0

    return InformationControlCheck(
        technique_used=technique,
        reveal_moments=reveals[:5],
        score=round(score, 2),
        notes=f"Technique: {technique}, {len(reveals)} reveal moments",
    )


def _check_agency(lines: list) -> AgencyCheck:
    """Check for hero agency in key moments."""
    decision_markers = ["decide", "choose", "step", "reach", "touch", "help", "enter"]
    passive_markers = ["forced", "pushed", "pulled", "taken", "removed", "extracted"]

    decisions = []
    risks = []

    for line in lines:
        text = line.text.lower()
        if any(marker in text for marker in decision_markers):
            decisions.append(line.line_id)
        if any(marker in text for marker in passive_markers):
            risks.append(f"{line.line_id}: passive action")

    # Score higher if decisions outnumber passive moments
    decision_ratio = len(decisions) / max(len(decisions) + len(risks), 1)
    score = decision_ratio * 100

    return AgencyCheck(
        hero_decisions=decisions[:5],
        deus_ex_machina_risks=risks[:3],
        score=round(max(40, score), 2),
        notes=f"{len(decisions)} active decisions, {len(risks)} passive moments",
    )


def _check_thematic_consistency(script: ScriptArtifact) -> ThematicConsistencyCheck:
    """Check for thematic consistency."""
    theme_words = script.theme.lower().split()
    logline_words = script.logline.lower().split()

    # Find theme keywords
    themes = [w for w in theme_words if len(w) > 4][:3]

    # Check for theme manifestation in lines
    manifestations = []
    for line in script.lines:
        text = line.text.lower()
        if any(theme in text for theme in themes):
            manifestations.append(line.line_id)

    # Score based on theme presence throughout
    if len(manifestations) >= 3:
        score = 80.0
    elif len(manifestations) >= 1:
        score = 60.0
    else:
        score = 40.0

    return ThematicConsistencyCheck(
        themes_identified=themes,
        theme_manifestations=manifestations[:5],
        score=round(score, 2),
        notes=f"Theme words: {themes}",
    )


def _check_motifs(lines: list) -> MotifCallbackCheck:
    """Check for recurring motifs."""
    # Look for repeated visual/action elements
    word_counts: dict[str, list[str]] = {}

    for line in lines:
        text = line.text.lower()
        # Focus on visual/concrete nouns
        visual_words = ["shimmer", "metallic", "red", "light", "pulse", "trace", "stain", "mark"]
        for word in visual_words:
            if word in text:
                if word not in word_counts:
                    word_counts[word] = []
                word_counts[word].append(line.line_id)

    # Find motifs (words appearing 2+ times)
    motifs = [word for word, occurrences in word_counts.items() if len(occurrences) >= 2]
    callbacks = []
    for word in motifs[:3]:
        occurrences = word_counts[word]
        if len(occurrences) >= 2:
            callbacks.append((occurrences[0], occurrences[-1]))

    score = min(100, len(motifs) * 25 + len(callbacks) * 15)

    return MotifCallbackCheck(
        motifs_found=motifs,
        callback_pairs=callbacks,
        score=round(max(50, score), 2),
        notes=f"Found {len(motifs)} recurring elements",
    )


def _check_surprise_balance(lines: list) -> SurpriseBalanceCheck:
    """Check balance between predictable and surprising moments."""
    surprise_markers = ["suddenly", "unexpected", "surprise", "shock", "snap", "abrupt"]
    setup_markers = ["wait", "prepare", "ready", "build", "approach"]

    surprising = []
    predictable = []

    for line in lines:
        text = line.text.lower()
        if any(marker in text for marker in surprise_markers):
            surprising.append(line.line_id)
        if any(marker in text for marker in setup_markers):
            predictable.append(line.line_id)

    # Good balance is roughly 70% setup, 30% surprise
    total = len(surprising) + len(predictable)
    if total == 0:
        score = 50.0
    else:
        surprise_ratio = len(surprising) / total
        # Optimal ratio around 0.3
        deviation = abs(surprise_ratio - 0.3)
        score = 100 - (deviation * 150)

    return SurpriseBalanceCheck(
        predictable_moments=predictable[:3],
        surprising_moments=surprising[:3],
        balance_score=round(max(40, min(100, score)), 2),
        notes=f"{len(surprising)} surprises, {len(predictable)} setups",
    )


def _check_promise_payoff(script: ScriptArtifact, lines: list) -> PromisePayoffCheck:
    """Check if opening promise is paid off in ending."""
    # Opening promise (first 5 lines + logline)
    opening_text = script.logline + " " + " ".join(line.text for line in lines[:5])
    opening_words = set(opening_text.lower().split())

    # Ending (last 5 lines + theme)
    ending_text = script.theme + " " + " ".join(line.text for line in lines[-5:])
    ending_words = set(ending_text.lower().split())

    # Check for thematic continuity
    promise_elements = [w for w in ["school", "pulse", "trace", "contrast"] if w in opening_words]
    payoff_elements = [w for w in ["radiology", "done", "calm", "relief", "safe"] if w in ending_words]

    # Check for tonal match
    opening_tone = "mysterious" if any(w in opening_text.lower() for w in ["strange", "hidden", "pulse"]) else "neutral"
    ending_tone = "resolved" if any(w in ending_text.lower() for w in ["done", "calm", "relief"]) else "ambiguous"

    contract_honored = len(payoff_elements) > 0 or ending_tone == "resolved"
    score = 70.0 if contract_honored else 50.0
    if len(promise_elements) > 0 and len(payoff_elements) > 0:
        score = 85.0

    return PromisePayoffCheck(
        promise_elements=promise_elements,
        payoff_elements=payoff_elements,
        contract_honored=contract_honored,
        score=round(score, 2),
        notes=f"Opening: {opening_tone}, Ending: {ending_tone}",
    )


def _check_pacing(lines: list) -> PacingTextureCheck:
    """Check pacing variety."""
    # Estimate pacing based on action vs dialogue and line density
    action_lines = [l for l in lines if l.kind == "action"]
    dialogue_lines = [l for l in lines if l.kind == "dialogue"]

    # Look for pacing shifts
    fast_markers = ["cut", "snap", "suddenly", "quick", "flash"]
    slow_markers = ["slowly", "calm", "pause", "hold", "steady"]

    fast_moments = [l.line_id for l in lines if any(m in l.text.lower() for m in fast_markers)]
    slow_moments = [l.line_id for l in lines if any(m in l.text.lower() for m in slow_markers)]

    # Determine rhythm pattern
    if len(fast_moments) > len(slow_moments) * 2:
        rhythm = "punchy throughout"
    elif len(slow_moments) > len(fast_moments) * 2:
        rhythm = "slow-burn"
    elif len(fast_moments) > 0 and len(slow_moments) > 0:
        rhythm = "waves (tension/release)"
    else:
        rhythm = "neutral"

    # Score based on variety
    has_contrast = len(fast_moments) > 0 and len(slow_moments) > 0
    score = 80.0 if has_contrast else 60.0

    return PacingTextureCheck(
        rhythm_pattern=rhythm,
        contrast_moments=fast_moments[:3] + slow_moments[:3],
        score=round(score, 2),
        notes=f"{len(fast_moments)} fast, {len(slow_moments)} slow moments",
    )


def _check_dialog_quality(dialogue_lines: list, characters: list[str]) -> DialogQualityCheck:
    """Check dialogue quality."""
    if not dialogue_lines:
        return DialogQualityCheck(
            has_subtext=False,
            distinct_voices=False,
            dialogue_line_count=0,
            score=60.0,  # No dialogue is okay for action-heavy scripts
            notes="No dialogue in script",
        )

    # Check for distinct voices (different speakers)
    speakers = {line.speaker for line in dialogue_lines if line.speaker}
    distinct_voices = len(speakers) >= 2

    # Check for subtext (lines that don't directly state intention)
    direct_markers = ["i want", "i need", "you must", "do this"]
    subtext_count = sum(
        1 for line in dialogue_lines
        if not any(marker in line.text.lower() for marker in direct_markers)
    )
    has_subtext = subtext_count > len(dialogue_lines) * 0.5

    score = 50.0
    if distinct_voices:
        score += 25
    if has_subtext:
        score += 25

    return DialogQualityCheck(
        has_subtext=has_subtext,
        distinct_voices=distinct_voices,
        dialogue_line_count=len(dialogue_lines),
        score=round(score, 2),
        notes=f"{len(speakers)} speakers, {subtext_count}/{len(dialogue_lines)} with subtext",
    )


def _check_economy(lines: list) -> EconomyFocusCheck:
    """Check for filler vs essential lines."""
    filler_markers = ["meanwhile", "also", "in addition", "furthermore"]
    essential_markers = [
        "cut", "reveal", "discover", "realize", "decide", "choose",
        "pulse", "red", "alarm", "extract", "done"
    ]

    filler = []
    essential_count = 0

    for line in lines:
        text = line.text.lower()
        if any(marker in text for marker in filler_markers):
            filler.append(line.line_id)
        if any(marker in text for marker in essential_markers):
            essential_count += 1

    ratio = (len(lines) - len(filler)) / max(len(lines), 1)
    score = ratio * 100

    return EconomyFocusCheck(
        filler_lines=filler[:5],
        essential_line_ratio=round(ratio, 2),
        score=round(score, 2),
        notes=f"{len(filler)} potential filler lines",
    )


def _check_causal_finale(lines: list) -> CausalFinaleCheck:
    """Check if finale feels inevitable yet surprising."""
    if len(lines) < 5:
        return CausalFinaleCheck(
            finale_inevitable=False,
            finale_surprising=False,
            score=40.0,
            notes="Script too short to evaluate finale",
        )

    # Check setup elements in first half
    first_half = lines[: len(lines) // 2]
    second_half = lines[len(lines) // 2 :]
    finale = lines[-5:]

    # Look for setup elements that payoff in finale
    setup_words = set()
    for line in first_half:
        words = line.text.lower().split()
        setup_words.update(w for w in words if len(w) > 4)

    payoff_words = set()
    for line in finale:
        words = line.text.lower().split()
        payoff_words.update(w for w in words if len(w) > 4)

    # Inevitable = setup words appear in finale
    overlap = setup_words & payoff_words
    inevitable = len(overlap) >= 3

    # Surprising = finale has new elements
    unique_finale = payoff_words - setup_words
    surprising = len(unique_finale) >= 2

    score = 50.0
    if inevitable:
        score += 25
    if surprising:
        score += 25

    return CausalFinaleCheck(
        finale_inevitable=inevitable,
        finale_surprising=surprising,
        score=round(score, 2),
        notes=f"{len(overlap)} setup payoffs, {len(unique_finale)} new elements",
    )
