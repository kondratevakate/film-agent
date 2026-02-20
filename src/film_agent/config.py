"""Runtime configuration loading."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, model_validator


class ModelCandidate(BaseModel):
    name: str
    weighted_score: float = Field(ge=0)
    physics: float = Field(ge=0)
    human_fidelity: float = Field(ge=0)
    identity: float = Field(ge=0)


class ProviderConfig(BaseModel):
    audio: str = "elevenlabs"
    image_primary: str = "openai_images"
    image_secondary: str = "nanobanana"
    video_primary: str = "sora"
    video_fallback: str = "hugsfield"


class Thresholds(BaseModel):
    gate0_physics_floor: float = 0.6
    gate0_human_fidelity_floor: float = 0.6
    gate0_identity_floor: float = 0.6

    videoscore2_threshold: float = 0.6
    vbench2_physics_floor: float = 0.6
    identity_drift_ceiling: float = 0.25
    regression_epsilon: float = 0.1

    shot_variety_min_types: int = 3
    max_consecutive_identical_framing: int = 2
    variety_score_threshold: float = 70.0
    final_score_floor: float = 70.0

    require_title_lock_on_retry: bool = True
    min_anchor_character_overlap_pct: float = 70.0
    min_anchor_fact_coverage_pct: float = 55.0
    min_script_faithfulness_score: float = 60.0
    min_narrative_coherence_score: float = 60.0
    min_style_anchor_quality: float = 55.0


class RetryLimits(BaseModel):
    gate1: int = 3
    gate2: int = 3
    gate3: int = 2


class RunConfig(BaseModel):
    project_name: str = "film-agent"
    reference_images: list[str] = Field(default_factory=list)
    creative_direction_file: str | None = None
    principles_file: str | None = None
    tokens_css_file: str | None = None
    duration_min_s: int = Field(default=60, ge=1, le=600)
    duration_max_s: int = Field(default=120, ge=1, le=600)
    duration_target_s: int = Field(default=95, ge=90, le=105)
    core_concepts: list[str] = Field(default_factory=list)
    model_candidates: list[ModelCandidate] = Field(default_factory=list)
    providers: ProviderConfig = Field(default_factory=ProviderConfig)
    thresholds: Thresholds = Field(default_factory=Thresholds)
    retry_limits: RetryLimits = Field(default_factory=RetryLimits)
    seed: int = 42
    resolution: str = "1920x1080"
    fps: int = 24

    @model_validator(mode="after")
    def validate_reference_images(self) -> "RunConfig":
        if self.reference_images and not 2 <= len(self.reference_images) <= 3:
            raise ValueError("reference_images must contain 2-3 paths when provided.")
        if self.creative_direction_file is not None and not self.creative_direction_file.strip():
            self.creative_direction_file = None
        if self.principles_file is not None and not self.principles_file.strip():
            self.principles_file = None
        if self.tokens_css_file is not None and not self.tokens_css_file.strip():
            self.tokens_css_file = None
        if self.duration_min_s >= self.duration_max_s:
            raise ValueError("duration_min_s must be strictly less than duration_max_s.")
        if not self.duration_min_s <= self.duration_target_s <= self.duration_max_s:
            raise ValueError("duration_target_s must be within [duration_min_s, duration_max_s].")
        return self


def load_config(config_path: Path) -> RunConfig:
    """Load and validate YAML config."""
    raw = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return RunConfig.model_validate(raw)


def config_dict_for_hash(config: RunConfig) -> dict[str, Any]:
    """Stable representation used for config hashing."""
    return config.model_dump(mode="json")
