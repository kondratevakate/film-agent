"""Role definitions and role-pack metadata."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class RoleId(StrEnum):
    SHOWRUNNER = "showrunner"
    DIRECTION = "direction"
    DANCE_MAPPING = "dance_mapping"
    CINEMATOGRAPHY = "cinematography"
    AUDIO = "audio"
    QA_JUDGE = "qa_judge"


@dataclass(frozen=True)
class RolePackManifest:
    role: RoleId
    required_inputs: tuple[str, ...]
    output_schema: str
    handoff_target: str | None


ROLE_PACKS: dict[RoleId, RolePackManifest] = {
    RoleId.SHOWRUNNER: RolePackManifest(
        role=RoleId.SHOWRUNNER,
        required_inputs=(),
        output_schema="schemas/showrunner.schema.json",
        handoff_target=RoleId.DIRECTION.value,
    ),
    RoleId.DIRECTION: RolePackManifest(
        role=RoleId.DIRECTION,
        required_inputs=("showrunner",),
        output_schema="schemas/direction.schema.json",
        handoff_target=RoleId.DANCE_MAPPING.value,
    ),
    RoleId.DANCE_MAPPING: RolePackManifest(
        role=RoleId.DANCE_MAPPING,
        required_inputs=("showrunner", "direction"),
        output_schema="schemas/dance_mapping.schema.json",
        handoff_target=RoleId.CINEMATOGRAPHY.value,
    ),
    RoleId.CINEMATOGRAPHY: RolePackManifest(
        role=RoleId.CINEMATOGRAPHY,
        required_inputs=("showrunner", "direction", "dance_mapping"),
        output_schema="schemas/cinematography.schema.json",
        handoff_target=RoleId.AUDIO.value,
    ),
    RoleId.AUDIO: RolePackManifest(
        role=RoleId.AUDIO,
        required_inputs=("showrunner", "direction", "dance_mapping"),
        output_schema="schemas/audio.schema.json",
        handoff_target=RoleId.QA_JUDGE.value,
    ),
    RoleId.QA_JUDGE: RolePackManifest(
        role=RoleId.QA_JUDGE,
        required_inputs=("showrunner", "direction", "dance_mapping", "cinematography", "audio"),
        output_schema="schemas/final_metrics.schema.json",
        handoff_target=None,
    ),
}


def list_roles() -> list[RoleId]:
    return sorted(ROLE_PACKS.keys(), key=lambda item: item.value)


def role_pack_root() -> Path:
    return Path(__file__).resolve().parents[2] / "roles"


def role_pack_dir(role: RoleId) -> Path:
    return role_pack_root() / role.value


def validate_role_pack_files(role: RoleId) -> list[str]:
    path = role_pack_dir(role)
    required = ("system.md", "task.md", "output_contract.md", "handoff.md", "schema.json")
    missing = [name for name in required if not (path / name).exists()]
    return missing
