from __future__ import annotations

from film_agent.final_mix import build_shot_timeline


def test_build_shot_timeline_accumulates_start_time() -> None:
    rows = [
        {"shot_id": "s1", "duration_s": 2.5},
        {"shot_id": "s2", "duration_s": 3.0},
        {"shot_id": "s3", "duration_s": 1.5},
    ]
    timeline = build_shot_timeline(rows)
    assert timeline[0]["start_s"] == 0.0
    assert timeline[1]["start_s"] == 2.5
    assert timeline[2]["start_s"] == 5.5


def test_build_shot_timeline_rejects_invalid_duration() -> None:
    rows = [{"shot_id": "s1", "duration_s": 0}]
    try:
        build_shot_timeline(rows)
    except ValueError as exc:
        assert "invalid duration_s" in str(exc)
    else:
        raise AssertionError("Expected ValueError")
