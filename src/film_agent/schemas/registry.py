"""Artifact registry by submitting agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel

from .artifacts import (
    AVPromptPackage,
    CinematographyQAResult,
    DryRunMetrics,
    EditorialTimeline,
    FinalMetrics,
    ImagePromptPackage,
    PatchArtifact,
    RenderPackage,
    ScriptArtifact,
    ScriptReviewArtifact,
    SelectedImagesArtifact,
    StoryQAResult,
)
from .references import ReferenceQAResult


@dataclass(frozen=True)
class AgentArtifact:
    model: Type[BaseModel]
    filename: str


AGENT_ARTIFACTS: dict[str, AgentArtifact] = {
    "showrunner": AgentArtifact(ScriptArtifact, "script.json"),
    "direction": AgentArtifact(ScriptReviewArtifact, "script_review.json"),
    "dance_mapping": AgentArtifact(ImagePromptPackage, "image_prompt_package.json"),
    "cinematography": AgentArtifact(SelectedImagesArtifact, "selected_images.json"),
    "audio": AgentArtifact(AVPromptPackage, "av_prompt_package.json"),
    "dryrun_metrics": AgentArtifact(DryRunMetrics, "dryrun_metrics.json"),
    "final_metrics": AgentArtifact(FinalMetrics, "final_metrics.json"),
    "timeline": AgentArtifact(EditorialTimeline, "editorial_timeline.json"),
    "render_package": AgentArtifact(RenderPackage, "render_package.json"),
    "story_qa": AgentArtifact(StoryQAResult, "story_qa.json"),
    "cinematography_qa": AgentArtifact(CinematographyQAResult, "cinematography_qa.json"),
    "reference_qa": AgentArtifact(ReferenceQAResult, "reference_qa.json"),
    "patch": AgentArtifact(PatchArtifact, "patch.json"),
}
