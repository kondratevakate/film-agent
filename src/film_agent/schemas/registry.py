"""Artifact registry by submitting agent."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Type

from pydantic import BaseModel

from .artifacts import (
    AVPromptPackage,
    DryRunMetrics,
    EditorialTimeline,
    FinalMetrics,
    ImagePromptPackage,
    RenderPackage,
    ScriptArtifact,
    ScriptReviewArtifact,
    SelectedImagesArtifact,
)


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
}
