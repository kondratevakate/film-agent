"""Prompt stack and role-pack helpers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from film_agent.roles import RoleId, role_pack_dir
from film_agent.resource_locator import find_resource_dir

if TYPE_CHECKING:
    from film_agent.config import RunConfig


MAIN_AGENT_OVERLAY = "main_agent_overlay.md"

AGENT_PROMPT_FILES: dict[str, str] = {
    "showrunner": "showrunner.md",
    "direction": "direction.md",
    "dance_mapping": "dance_mapping.md",
    "cinematography": "cinematography.md",
    "audio": "audio.md",
    "qa_judge": "qa_judge.md",
}


def list_agents() -> list[str]:
    return sorted(AGENT_PROMPT_FILES.keys())


def prompts_dir() -> Path:
    return find_resource_dir("prompts")


def get_prompt_stack(agent: str) -> str:
    if agent not in AGENT_PROMPT_FILES:
        raise ValueError(f"Unsupported prompt agent '{agent}'. Available: {', '.join(list_agents())}")

    agent_path = prompts_dir() / AGENT_PROMPT_FILES[agent]
    if not agent_path.exists():
        raise ValueError(f"Agent prompt file not found: {agent_path}")

    agent_text = agent_path.read_text(encoding="utf-8").strip()

    # The main overlay is applied to the main (showrunner) agent.
    if agent == "showrunner":
        overlay_path = prompts_dir() / MAIN_AGENT_OVERLAY
        if not overlay_path.exists():
            raise ValueError(f"Main agent overlay file not found: {overlay_path}")
        overlay_text = overlay_path.read_text(encoding="utf-8").strip()
        return (
            "### SYSTEM OVERLAY (MAIN AGENT)\n"
            f"{overlay_text}\n\n"
            "### AGENT ADDENDUM (SHOWRUNNER)\n"
            f"{agent_text}\n"
        )

    return agent_text + "\n"


def get_role_pack(role: str) -> dict[str, str]:
    try:
        role_id = RoleId(role)
    except ValueError as exc:
        allowed = ", ".join(item.value for item in RoleId)
        raise ValueError(f"Unsupported role '{role}'. Available: {allowed}") from exc

    pack_dir = role_pack_dir(role_id)
    if not pack_dir.exists():
        raise ValueError(f"Role pack directory not found: {pack_dir}")

    payload: dict[str, str] = {}
    for name in ("system.md", "task.md", "output_contract.md", "handoff.md", "schema.json"):
        path = pack_dir / name
        if not path.exists():
            raise ValueError(f"Role pack file missing: {path}")
        payload[name] = path.read_text(encoding="utf-8")
    return payload


def get_reference_context(config: "RunConfig", role: str) -> str:
    """Build reference library context for a specific role.

    Returns empty string if reference library is disabled.
    """
    if not config.reference_library.enabled:
        return ""

    from film_agent.reference_library import (
        build_reference_context_for_role,
        load_reference_library,
        load_reference_pack,
    )
    from film_agent.schemas.references import ReferencePack

    library = load_reference_library(config.reference_library)

    pack: ReferencePack | None = None
    if config.reference_library.reference_pack_file:
        try:
            pack = load_reference_pack(config.reference_library.reference_pack_file)
        except FileNotFoundError:
            pass

    return build_reference_context_for_role(role, library, pack)
