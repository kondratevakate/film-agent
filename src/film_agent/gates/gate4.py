"""Gate 4: final acceptance against immutable render contract."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from film_agent.continuity import (
    character_consistency_pct,
    load_story_anchor,
    narrative_coherence_score,
    script_faithfulness_pct,
    style_anchor_quality_score,
    title_matches_anchor,
)
from film_agent.config import RunConfig
from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.io.json_io import load_json
from film_agent.schemas.artifacts import (
    AVPromptPackage,
    FinalMetrics,
    FinalScorecard,
    GateReport,
    ImagePromptPackage,
    ScriptArtifact,
    SelectedImagesArtifact,
)
from film_agent.state_machine.state_store import RunStateData


def evaluate_gate4(run_path: Path, state: RunStateData, config: RunConfig) -> tuple[GateReport, FinalScorecard]:
    reasons: list[str] = []
    fixes: list[str] = []

    image_prompts = load_artifact_for_agent(run_path, state, "dance_mapping")
    selected_images = load_artifact_for_agent(run_path, state, "cinematography")
    av_prompts = load_artifact_for_agent(run_path, state, "audio")
    final_metrics = load_artifact_for_agent(run_path, state, "final_metrics")
    script = load_artifact_for_agent(run_path, state, "showrunner")
    if any(item is None for item in (image_prompts, selected_images, av_prompts, final_metrics)):
        reasons.append("Missing one or more required artifacts for Gate4 scoring.")
        fixes.append("Ensure image prompts, selected images, AV prompts and final metrics are submitted.")
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

    image_prompts = cast(ImagePromptPackage, image_prompts)
    selected_images = cast(SelectedImagesArtifact, selected_images)
    av_prompts = cast(AVPromptPackage, av_prompts)
    final_metrics = cast(FinalMetrics, final_metrics)
    script = cast(ScriptArtifact, script) if script is not None else None
    lock_payload = _load_lock_payload(run_path, state)
    spec_hash = lock_payload.get("spec_hash", "")
    if not spec_hash:
        reasons.append("Missing immutable spec hash in lock manifest.")
        fixes.append("Lock pre-production artifacts before final render.")

    if state.locked_spec_hash and spec_hash and state.locked_spec_hash != spec_hash:
        reasons.append("Run state locked_spec_hash does not match lock manifest.")
        fixes.append("Do not mutate lock manifest; recreate run if contract changed.")

    if not final_metrics.spec_hash:
        reasons.append("Final metrics must include the spec_hash used for render.")
        fixes.append("Populate final_metrics.spec_hash from the lock manifest.")
    elif spec_hash and final_metrics.spec_hash != spec_hash:
        reasons.append("Final metrics spec_hash does not match locked render contract.")
        fixes.append("Re-render with locked contract or restart as a new run.")

    if not final_metrics.one_shot_render:
        reasons.append("Final render must be flagged as one-shot execution.")
        fixes.append("Set one_shot_render=true only for single immutable render pass.")

    selected_count = len(selected_images.selected_images)
    selected_shot_ids = {item.shot_id for item in selected_images.selected_images}
    prompt_shot_ids = {item.shot_id for item in image_prompts.image_prompts}
    av_shot_ids = {item.shot_id for item in av_prompts.shot_prompts}

    selected_coverage = (len(selected_shot_ids & prompt_shot_ids) / max(len(selected_shot_ids), 1)) * 100.0
    av_coverage = (len(selected_shot_ids & av_shot_ids) / max(len(selected_shot_ids), 1)) * 100.0

    if selected_count < 3 or selected_count > 10:
        reasons.append("Selected images count must be between 3 and 10.")
        fixes.append("Select 3-10 representative images for the run manifest.")

    if selected_coverage < 100.0:
        reasons.append("Selected images include shot_ids missing from image prompt package.")
        fixes.append("Only select images from declared prompt shot_ids.")

    if av_coverage < 100.0:
        reasons.append("AV prompt package does not cover all selected shot_ids.")
        fixes.append("Add missing AV prompts for every selected shot.")

    if selected_images.image_prompt_package_id != state.latest_image_prompt_package_id:
        reasons.append("Selected images manifest is not linked to current image prompt package id.")
        fixes.append("Regenerate selected images manifest for the active prompt package.")

    if av_prompts.image_prompt_package_id != state.latest_image_prompt_package_id:
        reasons.append("AV prompt package image_prompt_package_id drifted from locked pre-production id.")
        fixes.append("Regenerate AV prompts from current image prompt package.")

    if av_prompts.selected_images_id != state.latest_selected_images_id:
        reasons.append("AV prompt package selected_images_id drifted from selected image manifest id.")
        fixes.append("Regenerate AV prompts after final image selection.")

    t = config.thresholds
    if final_metrics.videoscore2 < t.videoscore2_threshold:
        reasons.append("Final VideoScore2 below threshold.")
        fixes.append("Tune prompts/settings and rerun as a new run.")
    if final_metrics.vbench2_physics < t.vbench2_physics_floor:
        reasons.append("Final VBench2 physics below floor.")
        fixes.append("Improve motion/physics controllability and rerun.")
    if final_metrics.identity_drift > t.identity_drift_ceiling:
        reasons.append("Final identity drift above ceiling.")
        fixes.append("Strengthen identity anchors and rerun.")

    style_anchor_quality = style_anchor_quality_score(image_prompts.style_anchor)
    style_anchor_quality_ok = style_anchor_quality >= t.min_style_anchor_quality
    if not style_anchor_quality_ok:
        reasons.append("style_anchor quality is below configured floor.")
        fixes.append("Improve style_anchor specificity before final render.")

    story_anchor = load_story_anchor(run_path, state)
    story_anchor_present = story_anchor is not None
    anchor_title_match = True
    character_consistency = 100.0
    script_faithfulness = 100.0
    narrative_coherence = 100.0

    if script is None:
        reasons.append("Showrunner script is missing for final continuity checks.")
        fixes.append("Restore script artifact before Gate4 validation.")
        script_faithfulness = 0.0
        narrative_coherence = 0.0
        character_consistency = 0.0
        anchor_title_match = False
        story_anchor_present = False
    elif story_anchor is None:
        reasons.append("Story anchor is missing for final continuity checks.")
        fixes.append("Ensure story_anchor artifact exists from iteration 1.")
        script_faithfulness = 0.0
        character_consistency = 0.0
        anchor_title_match = False
        narrative_coherence = narrative_coherence_score(script)
    else:
        anchor_title_match = title_matches_anchor(story_anchor, script)
        character_consistency = character_consistency_pct(story_anchor, script)
        script_faithfulness = script_faithfulness_pct(story_anchor, script)
        narrative_coherence = narrative_coherence_score(script)

    if state.current_iteration > 1 and t.require_title_lock_on_retry and not anchor_title_match:
        reasons.append("Final script title drifted from story anchor.")
        fixes.append("Keep anchor title unchanged across retries and final render.")

    if character_consistency < t.min_anchor_character_overlap_pct:
        reasons.append("Final script character consistency is below configured floor.")
        fixes.append("Restore anchor character set and avoid cast replacement.")

    if script_faithfulness < t.min_script_faithfulness_score:
        reasons.append("Final script faithfulness is below configured floor.")
        fixes.append("Recover anchor beats in script and downstream prompts.")

    if narrative_coherence < t.min_narrative_coherence_score:
        reasons.append("Final narrative coherence is below configured floor.")
        fixes.append("Resolve discontinuities in script progression before final render.")

    script_lock_score = selected_coverage
    prompt_alignment_score = av_coverage
    cinematic_quality = max(0.0, min(100.0, final_metrics.videoscore2 * 100.0))
    consistency = max(0.0, min(100.0, (1.0 - final_metrics.identity_drift) * 100.0))
    audio_sync = max(0.0, min(100.0, final_metrics.audiosync_score))
    final_score = (
        0.35 * script_lock_score
        + 0.25 * prompt_alignment_score
        + 0.20 * cinematic_quality
        + 0.10 * consistency
        + 0.10 * audio_sync
    )
    scorecard = FinalScorecard(
        science_clarity=round(script_lock_score, 2),
        dance_mapping=round(prompt_alignment_score, 2),
        cinematic_quality=round(cinematic_quality, 2),
        consistency=round(consistency, 2),
        audio_sync=round(audio_sync, 2),
        final_score=round(max(0.0, min(100.0, final_score)), 2),
    )

    if scorecard.final_score < t.final_score_floor:
        reasons.append("Final score below acceptance floor.")
        fixes.append(f"Raise final score to at least {t.final_score_floor:.2f}.")

    # Generate identity checklist for manual verification
    identity_checklist = _generate_identity_checklist(script, image_prompts, config)

    passed = not reasons
    report = GateReport(
        gate="gate4",
        passed=passed,
        iteration=state.current_iteration,
        metrics={
            "videoscore2": final_metrics.videoscore2,
            "vbench2_physics": final_metrics.vbench2_physics,
            "identity_drift": final_metrics.identity_drift,
            "spec_hash": final_metrics.spec_hash,
            "locked_spec_hash": spec_hash,
            "one_shot_render": final_metrics.one_shot_render,
            "selected_images_count": selected_count,
            "selected_coverage_pct": round(selected_coverage, 2),
            "av_coverage_pct": round(av_coverage, 2),
            "final_score_floor": t.final_score_floor,
            "style_anchor_quality": round(style_anchor_quality, 2),
            "style_anchor_quality_ok": style_anchor_quality_ok,
            "story_anchor_present": story_anchor_present,
            "anchor_title_match": anchor_title_match,
            "character_consistency": round(character_consistency, 2),
            "script_faithfulness": round(script_faithfulness, 2),
            "narrative_coherence": round(narrative_coherence, 2),
            "science_clarity": round(scorecard.science_clarity, 2),
            "dance_mapping": round(scorecard.dance_mapping, 2),
            "cinematic_quality": round(scorecard.cinematic_quality, 2),
            "consistency": round(scorecard.consistency, 2),
            "audio_sync": round(scorecard.audio_sync, 2),
            "final_score": round(scorecard.final_score, 2),
            # Pre-render identity verification checklist
            "identity_checklist": identity_checklist,
        },
        reasons=reasons,
        fix_instructions=fixes,
    )
    return report, scorecard


def _load_lock_payload(run_path: Path, state: RunStateData) -> dict[str, object]:
    if state.preprod_locked_iteration is None:
        return {}
    lock_path = run_path / "locks" / f"preprod.iter-{state.preprod_locked_iteration:02d}.lock.json"
    if not lock_path.exists():
        return {}
    payload = load_json(lock_path)
    if isinstance(payload, dict):
        return payload
    return {}


def _generate_identity_checklist(
    script: ScriptArtifact | None,
    image_prompts: ImagePromptPackage,
    config: RunConfig,
) -> list[str]:
    """Generate checklist for manual identity verification before final render.

    Creates a list of items to verify:
    1. Cross-shot character appearance consistency
    2. Reference image matching (if configured)

    Returns:
        List of checklist items (max 8)
    """
    checklist: list[str] = []

    if script is None:
        checklist.append("WARNING: Script missing - cannot verify character list")
        return checklist

    # 1. Cross-shot consistency per character
    for char in script.characters:
        char_clean = char.strip()
        if not char_clean:
            continue

        shots_with_char = [
            item.shot_id
            for item in image_prompts.image_prompts
            if char_clean.lower() in item.image_prompt.lower()
        ]

        if len(shots_with_char) > 1:
            shot_list = ", ".join(shots_with_char[:4])
            if len(shots_with_char) > 4:
                shot_list += f" (+{len(shots_with_char) - 4} more)"
            checklist.append(f"Verify '{char_clean}' identity consistent across: {shot_list}")

    # 2. Reference image consistency (if configured)
    ref_entries = config.reference_image_entries()
    for ref in ref_entries:
        if ref.character:
            checklist.append(f"Verify '{ref.character}' matches reference image: {ref.path}")

    # 3. Generic identity checks
    if not checklist:
        checklist.append("Verify all characters maintain consistent appearance")

    return checklist[:8]  # Max 8 items
