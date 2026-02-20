from __future__ import annotations

from pathlib import Path

import pytest

from film_agent.automation.sdk_loop import auto_run_sdk_loop


def test_auto_run_requires_openai_credentials(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_SDK", raising=False)

    with pytest.raises(ValueError, match="OPENAI_API_KEY or OPENAI_SDK is required"):
        auto_run_sdk_loop(tmp_path, "run-does-not-matter")
