"""Gate 3: image prompt package checks."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from film_agent.continuity import style_anchor_quality_score
from film_agent.config import RunConfig
from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.schemas.artifacts import GateReport, ImagePromptPackage, ScriptArtifact
from film_agent.state_machine.state_store import RunStateData
from film_agent.gates.cinematography_qa import _analyze_cinematography
from film_agent.io.hashing import sha256_json
from typing import cast as typecast


def evaluate_gate3(run_path: Path, state: RunStateData, config: RunConfig) -> GateReport:
    reasons: list[str] = []
    fixes: list[str] = []

    image_prompts = load_artifact_for_agent(run_path, state, "dance_mapping")
    if image_prompts is None:
        reasons.append("Missing image prompt package artifact.")
        fixes.append("Submit image prompt package JSON before Gate3 validation.")
        return GateReport(
            gate="gate3",
            passed=False,
            iteration=state.current_iteration,
            metrics={
                "shot_count": 0,
                "shot_count_ok": False,
                "duplicate_shot_ids": 999,
                "short_prompts": 999,
                "review_link_ok": False,
                "style_anchor_present": False,
                "style_anchor_quality": 0.0,
                "style_anchor_quality_ok": False,
            },
            reasons=reasons,
            fix_instructions=fixes,
        )

    image_prompts = cast(ImagePromptPackage, image_prompts)
    items = image_prompts.image_prompts
    shot_count = len(items)
    shot_count_ok = 3 <= shot_count <= 10
    if not shot_count_ok:
        reasons.append(f"Image prompt count {shot_count} is outside [3, 10].")
        fixes.append("Provide between 3 and 10 representative image prompts.")

    shot_ids = [item.shot_id for item in items]
    duplicate_shot_ids = max(0, len(shot_ids) - len(set(shot_ids)))
    if duplicate_shot_ids > 0:
        reasons.append("Image prompt package contains duplicate shot_id values.")
        fixes.append("Ensure each image prompt uses a unique shot_id.")

    short_prompts = sum(1 for item in items if len(item.image_prompt.strip()) < 24)
    if short_prompts > 0:
        reasons.append("Some image prompts are too short to be reliably controllable.")
        fixes.append("Expand weak prompts with subject/action/composition details.")

    style_anchor_present = bool(image_prompts.style_anchor.strip())
    if not style_anchor_present:
        reasons.append("Image prompt package is missing style_anchor.")
        fixes.append("Provide a concise style anchor to preserve look and tone across shots.")

    style_anchor_quality = style_anchor_quality_score(image_prompts.style_anchor)
    style_anchor_quality_ok = style_anchor_quality >= config.thresholds.min_style_anchor_quality
    if not style_anchor_quality_ok:
        reasons.append("style_anchor quality is below configured floor.")
        fixes.append("Use a more specific style anchor with stable visual attributes.")

    missing_negative_constraints = sum(1 for item in items if not item.negative_prompt.strip())
    if missing_negative_constraints > 0:
        reasons.append("Some image prompts do not include negative constraints.")
        fixes.append("Add minimal negative constraints to reduce drift in previews.")

    review_link_ok = bool(state.latest_direction_pack_id and image_prompts.script_review_id == state.latest_direction_pack_id)
    if not review_link_ok:
        reasons.append("Image prompt package is not linked to current approved script review.")
        fixes.append("Rebuild prompt package with the latest script review id.")

    # =========================================================================
    # Cinematography QA: 8 Visual Production Gates (integrated)
    # =========================================================================
    script = load_artifact_for_agent(run_path, state, "showrunner")
    cinema_qa_passed = False
    cinema_qa_score = 0.0
    cinema_qa_gates_passed = 0
    cinema_qa_blocking = []
    # Character identity metrics
    char_identity_score = 100.0
    char_identity_issues: list[str] = []
    ref_identity_score = 100.0
    ref_identity_issues: list[str] = []

    if script is not None:
        script = typecast(ScriptArtifact, script)
        script_hash = sha256_json(script.model_dump(mode="json"))
        cinema_qa_result = _analyze_cinematography(
            script, image_prompts, script_hash, state.current_iteration, config
        )
        cinema_qa_passed = cinema_qa_result.passed
        cinema_qa_score = cinema_qa_result.overall_score
        cinema_qa_gates_passed = cinema_qa_result.gates_passed
        cinema_qa_blocking = cinema_qa_result.blocking_issues
        # Character identity metrics
        char_identity_score = cinema_qa_result.character_identity_score
        char_identity_issues = cinema_qa_result.character_identity_issues
        ref_identity_score = cinema_qa_result.reference_identity_score
        ref_identity_issues = cinema_qa_result.reference_identity_issues

        if not cinema_qa_passed:
            reasons.append(f"Cinematography QA failed: {cinema_qa_gates_passed}/8 gates passed, score {cinema_qa_score:.1f}/100.")
            for issue in cinema_qa_blocking[:3]:
                reasons.append(f"  - {issue}")
            for patch in cinema_qa_result.shot_patches[:3]:
                fixes.append(f"Shot {patch['shot_id']}: {patch['suggested_fix']}")
    else:
        reasons.append("Cannot evaluate Cinematography QA: missing script artifact.")
        fixes.append("Ensure script is submitted before image prompts.")

    passed = (
        shot_count_ok
        and duplicate_shot_ids == 0
        and short_prompts == 0
        and style_anchor_present
        and style_anchor_quality_ok
        and missing_negative_constraints == 0
        and review_link_ok
        and cinema_qa_passed  # NEW: 8 cinematography gates must pass
    )

    return GateReport(
        gate="gate3",
        passed=passed,
        iteration=state.current_iteration,
        metrics={
            "shot_count": shot_count,
            "shot_count_ok": shot_count_ok,
            "duplicate_shot_ids": duplicate_shot_ids,
            "short_prompts": short_prompts,
            "style_anchor_present": style_anchor_present,
            "style_anchor_quality": round(style_anchor_quality, 2),
            "style_anchor_quality_ok": style_anchor_quality_ok,
            "missing_negative_constraints": missing_negative_constraints,
            "review_link_ok": review_link_ok,
            "duration_target_s": config.duration_target_s,
            # Cinematography QA: 8 visual production gates
            "cinema_qa_passed": cinema_qa_passed,
            "cinema_qa_score": round(cinema_qa_score, 2),
            "cinema_qa_gates_passed": cinema_qa_gates_passed,
            "cinema_qa_blocking_issues": cinema_qa_blocking,
            # Character identity consistency
            "character_identity_score": round(char_identity_score, 2),
            "character_identity_issues": char_identity_issues[:3],
            "reference_identity_score": round(ref_identity_score, 2),
            "reference_identity_issues": ref_identity_issues[:3],
        },
        reasons=reasons,
        fix_instructions=fixes,
    )
