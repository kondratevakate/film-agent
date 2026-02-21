"""Artifact schemas."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


class ScriptLine(BaseModel):
    line_id: str
    kind: Literal["action", "dialogue"]
    text: str
    speaker: str | None = None
    est_duration_s: float = Field(gt=0)

    @model_validator(mode="after")
    def validate_dialogue_speaker(self) -> "ScriptLine":
        if self.kind == "dialogue" and not (self.speaker or "").strip():
            raise ValueError("dialogue lines must set speaker")
        return self


class ScriptArtifact(BaseModel):
    title: str
    logline: str
    theme: str = ""
    characters: list[str] = Field(min_length=1)
    locations: list[str] = Field(default_factory=list)
    lines: list[ScriptLine] = Field(min_length=1)


class StoryAnchorArtifact(BaseModel):
    title: str
    canonical_characters: list[str] = Field(min_length=1)
    must_keep_beats: list[str] = Field(min_length=1)
    style_anchor: str
    source_iteration: int = Field(ge=1, default=1)
    source_script_sha256: str | None = None


class ScriptReviewArtifact(BaseModel):
    script_version: int = Field(ge=1)
    script_hash_hint: str | None = None
    approved_story_facts: list[str] = Field(min_length=1)
    approved_character_registry: list[str] = Field(min_length=1)
    revision_notes: list[str] = Field(default_factory=list)
    unresolved_items: list[str] = Field(default_factory=list)
    lock_story_facts: bool = True


class ImagePromptItem(BaseModel):
    shot_id: str
    intent: str
    image_prompt: str
    negative_prompt: str = ""
    duration_s: float = Field(gt=0)


class ImagePromptPackage(BaseModel):
    script_review_id: str
    style_anchor: str
    image_prompts: list[ImagePromptItem] = Field(min_length=1)


class SelectedImage(BaseModel):
    shot_id: str
    image_path: str
    image_sha256: str | None = None
    notes: str = ""


class SelectedImagesArtifact(BaseModel):
    image_prompt_package_id: str
    selected_images: list[SelectedImage] = Field(min_length=3, max_length=10)


class AVPromptItem(BaseModel):
    shot_id: str
    video_prompt: str
    audio_prompt: str
    tts_text: str | None = None
    duration_s: float = Field(gt=0)


class AVPromptPackage(BaseModel):
    image_prompt_package_id: str
    selected_images_id: str
    music_prompt: str
    shot_prompts: list[AVPromptItem] = Field(min_length=1)
    global_negative_constraints: list[str] = Field(default_factory=list)


class Beat(BaseModel):
    beat_id: str
    start_s: float = Field(ge=0)
    end_s: float = Field(gt=0)
    science_claim: str
    dance_metaphor: str
    visual_motif: str
    emotion_intention: str
    spoken_line: str | None = None
    success_criteria: str
    science_status: Literal["ok", "critical_error"] = "ok"

    @model_validator(mode="after")
    def validate_times(self) -> "Beat":
        if self.end_s <= self.start_s:
            raise ValueError("end_s must be greater than start_s")
        return self


class BeatBible(BaseModel):
    concept_thesis: str
    beats: list[Beat] = Field(min_length=1)


class UserDirectionPack(BaseModel):
    iteration_goal: str
    style_references: list[str] = Field(min_length=1)
    must_include: list[str] = Field(default_factory=list)
    avoid: list[str] = Field(default_factory=list)
    notes: str = ""


class DanceMappingItem(BaseModel):
    beat_id: str
    motion_description: str
    symbolism: str
    motif_tag: str
    contrast_pattern: str


class DanceMappingSpec(BaseModel):
    direction_pack_id: str
    mappings: list[DanceMappingItem] = Field(min_length=1)


class Character(BaseModel):
    name: str
    identity_token: str
    costume_style_constraints: list[str] = Field(default_factory=list)
    forbidden_drift_rules: list[str] = Field(default_factory=list)


class CharacterBank(BaseModel):
    characters: list[Character] = Field(min_length=1)


class ShotDesignSheet(BaseModel):
    shot_id: str
    beat_id: str
    character: str
    identity_token: str
    background: str
    pose_action: str
    props: list[str] = Field(default_factory=list)
    camera: str
    framing: Literal["wide", "medium", "close", "extreme_close", "other"]
    lighting: str
    style_constraints: list[str] = Field(default_factory=list)
    duration_s: float = Field(gt=0)
    location: str
    continuity_reset: bool = False


class CinematographyPackage(BaseModel):
    character_bank: CharacterBank
    shots: list[ShotDesignSheet] = Field(min_length=1)


class VoiceLine(BaseModel):
    line_id: str
    timestamp_s: float = Field(ge=0)
    speaker: str
    text: str


class AudioCue(BaseModel):
    cue_id: str
    timestamp_s: float = Field(ge=0)
    duration_s: float = Field(ge=0)
    cue_type: Literal["music", "voiceover", "silence", "fx"]
    description: str


class AudioPlan(BaseModel):
    motifs: list[str] = Field(default_factory=list)
    voice_lines: list[VoiceLine] = Field(default_factory=list)
    cues: list[AudioCue] = Field(default_factory=list)
    sync_markers: list[float] = Field(default_factory=list)


class TimelineEntry(BaseModel):
    shot_id: str
    start_s: float = Field(ge=0)
    duration_s: float = Field(gt=0)


class EditorialTimeline(BaseModel):
    entries: list[TimelineEntry] = Field(min_length=1)


class RenderPackage(BaseModel):
    video_provider: str
    model_version: str
    seed: int
    sampler_settings: dict[str, Any] = Field(default_factory=dict)
    resolution: str
    fps: int = Field(gt=0)
    prompt_template_versions: dict[str, str] = Field(default_factory=dict)


class DryRunMetrics(BaseModel):
    videoscore2: float = Field(ge=0)
    vbench2_physics: float = Field(ge=0)
    identity_drift: float = Field(ge=0)
    blocking_issues: int = Field(ge=0)


class FinalMetrics(BaseModel):
    videoscore2: float = Field(ge=0)
    vbench2_physics: float = Field(ge=0)
    identity_drift: float = Field(ge=0)
    audiosync_score: float = Field(ge=0, le=100)
    consistency_score: float = Field(ge=0, le=100)
    spec_hash: str
    one_shot_render: bool = True


class GateReport(BaseModel):
    gate: str
    passed: bool
    iteration: int
    generated_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    metrics: dict[str, Any] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)
    fix_instructions: list[str] = Field(default_factory=list)


class FinalScorecard(BaseModel):
    science_clarity: float = Field(ge=0, le=100)
    dance_mapping: float = Field(ge=0, le=100)
    cinematic_quality: float = Field(ge=0, le=100)
    consistency: float = Field(ge=0, le=100)
    audio_sync: float = Field(ge=0, le=100)
    final_score: float = Field(ge=0, le=100)


# =============================================================================
# Story QA: 14 Storytelling Criteria
# =============================================================================


class DramaticQuestionCheck(BaseModel):
    """1. Dramatic Question - what question does the viewer wait to answer?"""

    present: bool
    question_text: str = ""
    clarity_score: float = Field(ge=0, le=100)
    notes: str = ""


class CauseEffectCheck(BaseModel):
    """2. Cause-Effect Chain - scenes force the next, not just follow."""

    chain_intact: bool
    breaks: list[str] = Field(default_factory=list)  # line_ids where chain breaks
    score: float = Field(ge=0, le=100)
    notes: str = ""


class ConflictCheck(BaseModel):
    """3. Conflict as scene driver - goal, obstacle, tactic, outcome per scene."""

    scenes_with_conflict: int = 0
    scenes_missing_conflict: list[str] = Field(default_factory=list)  # locations
    score: float = Field(ge=0, le=100)
    notes: str = ""


class StakesEscalationCheck(BaseModel):
    """4. Stakes progression - stakes grow: complexity, cost, irreversibility."""

    escalation_detected: bool
    progression: list[str] = Field(default_factory=list)  # ordered stake levels
    score: float = Field(ge=0, le=100)
    notes: str = ""


class InformationControlCheck(BaseModel):
    """5. Reveals & Withholding - dramatic irony, mystery, recontextualization."""

    technique_used: Literal["dramatic_irony", "mystery", "reframe", "none"] = "none"
    reveal_moments: list[str] = Field(default_factory=list)  # line_ids
    score: float = Field(ge=0, le=100)
    notes: str = ""


class AgencyCheck(BaseModel):
    """6. Hero decisions - key moments result from hero choice, not chance."""

    hero_decisions: list[str] = Field(default_factory=list)  # line_ids
    deus_ex_machina_risks: list[str] = Field(default_factory=list)
    score: float = Field(ge=0, le=100)
    notes: str = ""


class ThematicConsistencyCheck(BaseModel):
    """7. Thematic consistency - 1-2 theses proven through hero actions."""

    themes_identified: list[str] = Field(default_factory=list)
    theme_manifestations: list[str] = Field(default_factory=list)  # line_ids
    score: float = Field(ge=0, le=100)
    notes: str = ""


class MotifCallbackCheck(BaseModel):
    """8. Motifs & Callbacks - repeated image/phrase that changes meaning."""

    motifs_found: list[str] = Field(default_factory=list)
    callback_pairs: list[tuple[str, str]] = Field(default_factory=list)  # (setup, payoff)
    score: float = Field(ge=0, le=100)
    notes: str = ""


class SurpriseBalanceCheck(BaseModel):
    """9. Predictability/Surprise balance - logical yet unexpected."""

    predictable_moments: list[str] = Field(default_factory=list)
    surprising_moments: list[str] = Field(default_factory=list)
    balance_score: float = Field(ge=0, le=100)
    notes: str = ""


class PromisePayoffCheck(BaseModel):
    """10. Promise & Payoff - opening promises genre/tone, ending delivers."""

    promise_elements: list[str] = Field(default_factory=list)
    payoff_elements: list[str] = Field(default_factory=list)
    contract_honored: bool = True
    score: float = Field(ge=0, le=100)
    notes: str = ""


class PacingTextureCheck(BaseModel):
    """11. Pacing & Texture - contrast: tension/release, fast/slow, internal/external."""

    rhythm_pattern: str = ""  # e.g. "slow-burn -> punchy" or "waves"
    contrast_moments: list[str] = Field(default_factory=list)
    score: float = Field(ge=0, le=100)
    notes: str = ""


class DialogQualityCheck(BaseModel):
    """12. Dialog Quality - subtext, action in speech, distinct voices."""

    has_subtext: bool = False
    distinct_voices: bool = False
    dialogue_line_count: int = 0
    score: float = Field(ge=0, le=100)
    notes: str = ""


class EconomyFocusCheck(BaseModel):
    """13. Economy & Focus - every element serves question/arc/theme/stakes/twist."""

    filler_lines: list[str] = Field(default_factory=list)  # line_ids
    essential_line_ratio: float = Field(ge=0, le=1)
    score: float = Field(ge=0, le=100)
    notes: str = ""


class CausalFinaleCheck(BaseModel):
    """14. Causal Finale - ending feels inevitable yet surprising."""

    finale_inevitable: bool = False
    finale_surprising: bool = False
    score: float = Field(ge=0, le=100)
    notes: str = ""


class StoryQAResult(BaseModel):
    """Complete Story QA evaluation with all 14 criteria."""

    script_hash: str
    iteration: int

    # 14 criteria checks
    dramatic_question: DramaticQuestionCheck
    cause_effect: CauseEffectCheck
    conflict: ConflictCheck
    stakes_escalation: StakesEscalationCheck
    information_control: InformationControlCheck
    agency: AgencyCheck
    thematic_consistency: ThematicConsistencyCheck
    motif_callback: MotifCallbackCheck
    surprise_balance: SurpriseBalanceCheck
    promise_payoff: PromisePayoffCheck
    pacing_texture: PacingTextureCheck
    dialog_quality: DialogQualityCheck
    economy_focus: EconomyFocusCheck
    causal_finale: CausalFinaleCheck

    # Aggregate
    overall_score: float = Field(ge=0, le=100)
    blocking_issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    passed: bool = False


# =============================================================================
# Patch Mechanism
# =============================================================================


# =============================================================================
# Cinematography QA: 8 Visual Production Gates
# =============================================================================


class StorySupport(BaseModel):
    """G1. Story Support - each shot has intention tied to goal/obstacle/outcome."""

    shots_with_intention: int = 0
    decorative_shots: list[str] = Field(default_factory=list)  # shot_ids
    score: float = Field(ge=0, le=100)
    passed: bool = False
    notes: str = ""


class GeographicClarity(BaseModel):
    """G2. Geographic Clarity - viewer can track spatial relations."""

    establishing_shots_present: bool = False
    unclear_transitions: list[str] = Field(default_factory=list)  # shot_ids
    score: float = Field(ge=0, le=100)
    passed: bool = False
    notes: str = ""


class SuspenseEscalation(BaseModel):
    """G3. Suspense Escalation Pattern - visual language tightens across film."""

    escalation_moves: list[str] = Field(default_factory=list)  # descriptions
    escalation_count: int = 0
    score: float = Field(ge=0, le=100)
    passed: bool = False  # needs at least 3 escalating moves
    notes: str = ""


class InformationControlVisual(BaseModel):
    """G4. Information Control - lighting/framing control reveal vs withhold."""

    controlled_shots: list[str] = Field(default_factory=list)  # shot_ids
    evenly_lit_shots: list[str] = Field(default_factory=list)  # shot_ids with no ambiguity
    score: float = Field(ge=0, le=100)
    passed: bool = False
    notes: str = ""


class StyleConsistency(BaseModel):
    """G5. Consistency / No Style Drift - follows Look Bible rules."""

    style_violations: list[str] = Field(default_factory=list)  # shot_ids with drift
    score: float = Field(ge=0, le=100)
    passed: bool = False
    notes: str = ""


class TechnicalFeasibility(BaseModel):
    """G6. Technical Feasibility - prompts are renderable."""

    infeasible_shots: list[str] = Field(default_factory=list)  # shot_ids
    contradictions: list[str] = Field(default_factory=list)  # descriptions
    score: float = Field(ge=0, le=100)
    passed: bool = False
    notes: str = ""


class ContinuityProgression(BaseModel):
    """G7. Continuity & Progression - wardrobe/props consistent with time."""

    continuity_gaps: list[str] = Field(default_factory=list)  # shot_ids
    progression_issues: list[str] = Field(default_factory=list)
    score: float = Field(ge=0, le=100)
    passed: bool = False
    notes: str = ""


class ReviewFriendliness(BaseModel):
    """G8. Manual Review Friendliness - shots clear enough to approve/reject."""

    vague_shots: list[str] = Field(default_factory=list)  # shot_ids
    score: float = Field(ge=0, le=100)
    passed: bool = False
    notes: str = ""


class LookBible(BaseModel):
    """Look Bible - visual rules for the production."""

    palette: str = ""
    lighting_philosophy: str = ""
    lens_language: str = ""
    camera_movement_rules: str = ""
    composition_rules: str = ""
    texture_rules: str = ""
    escalation_plan: str = ""


class CinematographyQAResult(BaseModel):
    """Complete Cinematography QA evaluation with 8 gates."""

    script_hash: str
    iteration: int

    # Look Bible (extracted from creative direction)
    look_bible: LookBible

    # 8 gates
    g1_story_support: StorySupport
    g2_geographic_clarity: GeographicClarity
    g3_suspense_escalation: SuspenseEscalation
    g4_information_control: InformationControlVisual
    g5_style_consistency: StyleConsistency
    g6_technical_feasibility: TechnicalFeasibility
    g7_continuity_progression: ContinuityProgression
    g8_review_friendliness: ReviewFriendliness

    # Character identity consistency (additional checks beyond 8 gates)
    character_identity_score: float = Field(default=100.0, ge=0, le=100)
    character_identity_issues: list[str] = Field(default_factory=list)
    reference_identity_score: float = Field(default=100.0, ge=0, le=100)
    reference_identity_issues: list[str] = Field(default_factory=list)

    # Aggregate
    gates_passed: int = Field(ge=0, le=8)
    overall_score: float = Field(ge=0, le=100)
    blocking_issues: list[str] = Field(default_factory=list)
    shot_patches: list[dict] = Field(default_factory=list)  # suggested fixes
    previs_checklist: list[str] = Field(default_factory=list)
    passed: bool = False


class PatchOperation(BaseModel):
    """Single patch operation on an artifact."""

    path: str  # JSON path e.g. "lines[5].text" or "logline"
    operation: Literal["replace", "delete", "insert"]
    old_value: Any | None = None  # for verification
    new_value: Any | None = None
    rationale: str = ""


class PatchArtifact(BaseModel):
    """Manual patch request for deterministic artifact correction."""

    target_artifact: Literal[
        "script", "script_review", "image_prompt_package", "av_prompt_package"
    ]
    target_iteration: int = Field(ge=1)
    target_artifact_hash: str  # SHA256 to verify we're patching the right version
    operations: list[PatchOperation] = Field(min_length=1)
    rationale: str
    author: str = "human"
