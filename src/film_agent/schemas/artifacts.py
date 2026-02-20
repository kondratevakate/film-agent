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
