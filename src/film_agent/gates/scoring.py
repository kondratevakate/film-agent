"""Scoring utilities for QA/Judge stage."""

from __future__ import annotations

from film_agent.schemas.artifacts import (
    AudioPlan,
    BeatBible,
    CinematographyPackage,
    DanceMappingSpec,
    FinalMetrics,
    FinalScorecard,
    UserDirectionPack,
)


def clamp_score(value: float) -> float:
    return max(0.0, min(100.0, value))


def compute_science_clarity(beat_bible: BeatBible, concept_coverage_pct: float, critical_errors: int) -> float:
    base = concept_coverage_pct
    if critical_errors > 0:
        base -= min(80.0, critical_errors * 25.0)
    if not beat_bible.beats:
        return 0.0
    return clamp_score(base)


def compute_dance_mapping_score(
    beat_bible: BeatBible,
    dance_mapping: DanceMappingSpec,
    direction_pack: UserDirectionPack,
) -> float:
    beat_ids = {beat.beat_id for beat in beat_bible.beats}
    mapped_ids = {mapping.beat_id for mapping in dance_mapping.mappings}

    coverage_ratio = len(beat_ids & mapped_ids) / max(len(beat_ids), 1)
    coverage_score = coverage_ratio * 100.0

    combined_text = " ".join(
        f"{m.motion_description} {m.symbolism} {m.motif_tag} {m.contrast_pattern}".lower()
        for m in dance_mapping.mappings
    )
    must_include = [token.lower() for token in direction_pack.must_include]
    avoid = [token.lower() for token in direction_pack.avoid]

    must_hits = sum(1 for token in must_include if token in combined_text)
    must_ratio = must_hits / max(len(must_include), 1) if must_include else 1.0
    must_score = must_ratio * 100.0

    avoid_hits = sum(1 for token in avoid if token in combined_text)
    avoid_penalty = (avoid_hits / max(len(avoid), 1) * 100.0) if avoid else 0.0

    alignment_score = clamp_score(must_score - avoid_penalty)
    return clamp_score(0.6 * coverage_score + 0.4 * alignment_score)


def compute_cinematic_quality(
    cinematography: CinematographyPackage,
    continuity_violations: int,
    variety_score: float,
) -> float:
    shot_count = max(len(cinematography.shots), 1)
    continuity_component = clamp_score(100.0 - (continuity_violations / shot_count) * 100.0)
    return clamp_score(0.5 * continuity_component + 0.5 * variety_score)


def compute_consistency(metrics: FinalMetrics) -> float:
    physics_component = clamp_score(metrics.vbench2_physics * 100.0)
    identity_component = clamp_score(100.0 - metrics.identity_drift * 100.0)
    return clamp_score(0.6 * physics_component + 0.4 * identity_component)


def compute_audio_sync(audio_plan: AudioPlan, final_metrics: FinalMetrics) -> float:
    if not audio_plan.cues and not audio_plan.voice_lines:
        return clamp_score(final_metrics.audiosync_score)

    event_points = [line.timestamp_s for line in audio_plan.voice_lines]
    for cue in audio_plan.cues:
        event_points.extend((cue.timestamp_s, cue.timestamp_s + cue.duration_s))

    min_t = min(event_points) if event_points else 0.0
    max_t = max(event_points) if event_points else 0.0
    markers = audio_plan.sync_markers

    is_sorted = all(markers[i] <= markers[i + 1] for i in range(max(len(markers) - 1, 0)))
    order_score = 100.0 if is_sorted else 40.0
    marker_presence_score = 100.0 if markers else 35.0

    if markers:
        in_window = sum(1 for marker in markers if min_t <= marker <= max_t)
        marker_coverage_score = (in_window / len(markers)) * 100.0
    else:
        marker_coverage_score = 35.0

    duration_score = 100.0 if max_t > min_t else 30.0
    rule_based = (
        0.30 * order_score
        + 0.30 * marker_coverage_score
        + 0.20 * marker_presence_score
        + 0.20 * duration_score
    )
    return clamp_score(0.65 * final_metrics.audiosync_score + 0.35 * rule_based)


def build_final_scorecard(
    science_clarity: float,
    dance_mapping: float,
    cinematic_quality: float,
    consistency: float,
    audio_sync: float,
) -> FinalScorecard:
    final_score = clamp_score(
        0.35 * science_clarity
        + 0.25 * dance_mapping
        + 0.20 * cinematic_quality
        + 0.10 * consistency
        + 0.10 * audio_sync
    )
    return FinalScorecard(
        science_clarity=clamp_score(science_clarity),
        dance_mapping=clamp_score(dance_mapping),
        cinematic_quality=clamp_score(cinematic_quality),
        consistency=clamp_score(consistency),
        audio_sync=clamp_score(audio_sync),
        final_score=final_score,
    )
