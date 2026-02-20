from __future__ import annotations

from film_agent.render_qc import decide_qc_outcome


def test_decide_qc_outcome_pass() -> None:
    decision, reasons = decide_qc_outcome(
        score=0.81,
        threshold=0.75,
        retries_used=0,
        retry_limit=2,
        judge_available=True,
    )
    assert decision == "pass"
    assert "score_above_threshold" in reasons


def test_decide_qc_outcome_retry_then_fail() -> None:
    decision1, reasons1 = decide_qc_outcome(
        score=0.6,
        threshold=0.75,
        retries_used=1,
        retry_limit=2,
        judge_available=True,
    )
    assert decision1 == "retry"
    assert reasons1 == ["score_below_threshold"]

    decision2, reasons2 = decide_qc_outcome(
        score=0.6,
        threshold=0.75,
        retries_used=2,
        retry_limit=2,
        judge_available=True,
    )
    assert decision2 == "fail"
    assert "retry_limit_reached" in reasons2


def test_decide_qc_outcome_judge_unavailable() -> None:
    decision, reasons = decide_qc_outcome(
        score=None,
        threshold=0.75,
        retries_used=0,
        retry_limit=2,
        judge_available=False,
    )
    assert decision == "fail"
    assert reasons == ["judge_unavailable"]
