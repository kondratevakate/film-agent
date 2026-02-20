from __future__ import annotations

from pathlib import Path

import pytest

from film_agent.prompt_packets import lint_prompt_packet
from film_agent.prompts import get_prompt_stack
from film_agent.roles import RoleId, list_roles, validate_role_pack_files


def test_role_id_contains_expected_roles() -> None:
    values = {role.value for role in list_roles()}
    assert values == {"showrunner", "direction", "dance_mapping", "cinematography", "audio", "qa_judge"}


def test_role_pack_files_exist() -> None:
    for role in list_roles():
        missing = validate_role_pack_files(role)
        assert missing == []


def test_prompt_lint_for_showrunner_passes() -> None:
    prompt = (
        "## System\nReturn JSON only. 5-second one primary action continuity close-up adjacent shots.\n\n"
        "## Project Constraints\n{}\n\n"
        "## Iteration Context\nx\n\n"
        "## Output Contract\n{}\n"
    )
    errors = lint_prompt_packet(prompt, RoleId.SHOWRUNNER)
    assert errors == []


def test_show_prompt_stack_available() -> None:
    value = get_prompt_stack("showrunner")
    assert "SYSTEM OVERLAY" in value
    assert "Return JSON only." in value
    assert "Shot-by-shot Script: Minimum of 10 shots" not in value
