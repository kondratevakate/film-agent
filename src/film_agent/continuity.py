"""Story anchor persistence and continuity scoring helpers."""

from __future__ import annotations

from pathlib import Path
import re

from film_agent.io.hashing import sha256_json
from film_agent.io.json_io import load_json
from film_agent.schemas.artifacts import ScriptArtifact, StoryAnchorArtifact
from film_agent.state_machine.state_store import RunStateData, iteration_key


_STOPWORDS = {
    "a",
    "an",
    "and",
    "are",
    "as",
    "at",
    "be",
    "by",
    "for",
    "from",
    "in",
    "into",
    "is",
    "it",
    "its",
    "of",
    "on",
    "or",
    "that",
    "the",
    "their",
    "them",
    "this",
    "to",
    "with",
}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _tokens(text: str) -> list[str]:
    return re.findall(r"[a-zA-Z0-9']+", text.casefold())


def _keyword_set(text: str) -> set[str]:
    return {item for item in _tokens(text) if len(item) >= 4 and item not in _STOPWORDS}


def _derive_style_anchor(script: ScriptArtifact) -> str:
    source = script.theme.strip() or script.logline.strip() or script.title.strip()
    words = _tokens(source)
    if not words:
        return "grounded cinematic continuity"
    return " ".join(words[:8])


def _extract_must_keep_beats(script: ScriptArtifact, limit: int = 6) -> list[str]:
    beats: list[str] = []
    for line in script.lines:
        text = line.text.strip()
        if not text:
            continue
        lower = text.casefold()
        if "todo" in lower or "tbd" in lower or ("<" in text and ">" in text):
            continue
        beats.append(text)
        if len(beats) >= limit:
            break
    if beats:
        return beats
    return [script.logline.strip() or script.title.strip() or "core story beat"]


def build_story_anchor(
    script: ScriptArtifact,
    *,
    source_iteration: int = 1,
    source_script_sha256: str | None = None,
) -> StoryAnchorArtifact:
    return StoryAnchorArtifact(
        title=script.title.strip(),
        canonical_characters=[item.strip() for item in script.characters if item.strip()],
        must_keep_beats=_extract_must_keep_beats(script),
        style_anchor=_derive_style_anchor(script),
        source_iteration=source_iteration,
        source_script_sha256=source_script_sha256 or sha256_json(script.model_dump(mode="json")),
    )


def load_anchor_script(run_path: Path, state: RunStateData) -> ScriptArtifact | None:
    record = state.iterations.get(iteration_key(1))
    if not record:
        return None
    item = record.artifacts.get("showrunner")
    if not item:
        return None
    path = Path(item.path)
    if not path.exists():
        return None
    return ScriptArtifact.model_validate(load_json(path))


def load_story_anchor(run_path: Path, state: RunStateData) -> StoryAnchorArtifact | None:
    record = state.iterations.get(iteration_key(1))
    if record:
        item = record.artifacts.get("story_anchor")
        if item:
            path = Path(item.path)
            if path.exists():
                return StoryAnchorArtifact.model_validate(load_json(path))

    fallback = run_path / "iterations" / iteration_key(1) / "artifacts" / "story_anchor.json"
    if fallback.exists():
        return StoryAnchorArtifact.model_validate(load_json(fallback))

    anchor_script = load_anchor_script(run_path, state)
    if anchor_script is None:
        return None
    return build_story_anchor(anchor_script, source_iteration=1)


def title_matches_anchor(anchor: StoryAnchorArtifact, script: ScriptArtifact) -> bool:
    return anchor.title.strip().casefold() == script.title.strip().casefold()


def character_consistency_pct(anchor: StoryAnchorArtifact, script: ScriptArtifact) -> float:
    expected = {item.strip().casefold() for item in anchor.canonical_characters if item.strip()}
    current = {item.strip().casefold() for item in script.characters if item.strip()}
    if not expected:
        return 100.0
    return (len(expected & current) / len(expected)) * 100.0


def script_faithfulness_pct(anchor: StoryAnchorArtifact, script: ScriptArtifact) -> float:
    if not anchor.must_keep_beats:
        return 100.0

    haystack = " ".join([script.title, script.logline, script.theme, *(line.text for line in script.lines)])
    haystack_terms = _keyword_set(haystack)
    if not haystack_terms:
        return 0.0

    hits = 0
    for beat in anchor.must_keep_beats:
        beat_terms = _keyword_set(beat)
        if not beat_terms:
            continue
        if beat_terms & haystack_terms:
            hits += 1
    return (hits / len(anchor.must_keep_beats)) * 100.0


def narrative_coherence_score(script: ScriptArtifact) -> float:
    penalty = 0.0
    line_count = len(script.lines)
    if line_count < 10:
        penalty += 20.0

    has_actions = any(line.kind == "action" for line in script.lines)
    has_dialogue = any(line.kind == "dialogue" for line in script.lines)
    if not has_actions:
        penalty += 20.0
    if not has_dialogue:
        penalty += 20.0

    if not script.title.strip() or not script.logline.strip() or not script.theme.strip():
        penalty += 12.0

    if len([item for item in script.locations if item.strip()]) < 2:
        penalty += 10.0

    placeholder_hits = sum(
        1
        for line in script.lines
        if "todo" in line.text.casefold() or "tbd" in line.text.casefold() or ("<" in line.text and ">" in line.text)
    )
    if placeholder_hits:
        penalty += min(28.0, placeholder_hits * 12.0)

    chained_hits = sum(1 for line in script.lines if re.search(r"\b(and then|while|before|after)\b", line.text.casefold()))
    if chained_hits:
        penalty += min(18.0, chained_hits * 3.0)

    return _clamp(100.0 - penalty)


def style_anchor_quality_score(value: str) -> float:
    tokens = _tokens(value)
    if not tokens:
        return 0.0

    length_score = min(70.0, len(tokens) * 14.0)
    unique_ratio = len(set(tokens)) / max(len(tokens), 1)
    diversity_score = unique_ratio * 20.0
    specificity_bonus = 10.0 if len(tokens) >= 3 else 0.0
    return _clamp(length_score + diversity_score + specificity_bonus)
