"""Gate 3: image prompt package checks."""

from __future__ import annotations

from pathlib import Path
from typing import cast

from film_agent.continuity import style_anchor_quality_score
from film_agent.config import RunConfig
from film_agent.io.artifact_store import load_artifact_for_agent
from film_agent.schemas.artifacts import GateReport, ImagePromptPackage
from film_agent.state_machine.state_store import RunStateData


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

    passed = (
        shot_count_ok
        and duplicate_shot_ids == 0
        and short_prompts == 0
        and style_anchor_present
        and style_anchor_quality_ok
        and missing_negative_constraints == 0
        and review_link_ok
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
        },
        reasons=reasons,
        fix_instructions=fixes,
    )
