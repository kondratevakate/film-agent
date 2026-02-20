"""Project constants."""

from __future__ import annotations

from enum import StrEnum


class RunState(StrEnum):
    INIT = "INIT"
    GATE0 = "GATE0"
    COLLECT_SHOWRUNNER = "COLLECT_SHOWRUNNER"
    COLLECT_DIRECTION = "COLLECT_DIRECTION"
    COLLECT_DANCE_MAPPING = "COLLECT_DANCE_MAPPING"
    COLLECT_CINEMATOGRAPHY = "COLLECT_CINEMATOGRAPHY"
    COLLECT_AUDIO = "COLLECT_AUDIO"
    LOCK_PREPROD = "LOCK_PREPROD"
    GATE1 = "GATE1"
    GATE2 = "GATE2"
    DRYRUN = "DRYRUN"
    GATE3 = "GATE3"
    FINAL_RENDER = "FINAL_RENDER"
    GATE4 = "GATE4"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"


GATE_NAMES = ("gate0", "gate1", "gate2", "gate3", "gate4")


AGENT_NAMES = (
    "showrunner",
    "direction",
    "dance_mapping",
    "cinematography",
    "audio",
    "dryrun_metrics",
    "final_metrics",
    "timeline",
    "render_package",
)


REQUIRED_PREPROD_ARTIFACTS = (
    "showrunner",
    "direction",
    "dance_mapping",
    "cinematography",
    "audio",
)
