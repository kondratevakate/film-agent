"""Artifact registry by submitting agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel

from .artifacts import (
    AudioPlan,
    BeatBible,
    CinematographyPackage,
    DanceMappingSpec,
    DryRunMetrics,
    EditorialTimeline,
    FinalMetrics,
    RenderPackage,
    UserDirectionPack,
)


@dataclass(frozen=True)
class AgentArtifact:
    model: Type[BaseModel]
    filename: str


AGENT_ARTIFACTS: dict[str, AgentArtifact] = {
    "showrunner": AgentArtifact(BeatBible, "beat_bible.json"),
    "direction": AgentArtifact(UserDirectionPack, "user_direction_pack.json"),
    "dance_mapping": AgentArtifact(DanceMappingSpec, "dance_mapping_spec.json"),
    "cinematography": AgentArtifact(CinematographyPackage, "shot_design_sheets.json"),
    "audio": AgentArtifact(AudioPlan, "audio_plan.json"),
    "dryrun_metrics": AgentArtifact(DryRunMetrics, "dryrun_metrics.json"),
    "final_metrics": AgentArtifact(FinalMetrics, "final_metrics.json"),
    "timeline": AgentArtifact(EditorialTimeline, "editorial_timeline.json"),
    "render_package": AgentArtifact(RenderPackage, "render_package.json"),
}
