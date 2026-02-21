"""Reference library loader and utilities."""

from __future__ import annotations

import json
from pathlib import Path

from film_agent.config import ReferenceLibraryConfig
from film_agent.resource_locator import find_resource_dir
from film_agent.schemas.references import (
    BeatCard,
    Reference,
    ReferenceLibrary,
    ReferencePack,
)


def references_dir() -> Path:
    """Get the references resource directory."""
    # Try embedded resources first
    embedded_dir = Path(__file__).parent / "resources" / "references"
    if embedded_dir.is_dir():
        return embedded_dir
    return find_resource_dir("references")


def load_refs(config: ReferenceLibraryConfig | None = None) -> list[Reference]:
    """Load all references from refs.json or custom path."""
    if config and config.refs_file:
        refs_path = Path(config.refs_file)
    else:
        refs_path = references_dir() / "refs.json"

    if not refs_path.exists():
        return []

    raw = json.loads(refs_path.read_text(encoding="utf-8"))
    return [Reference.model_validate(item) for item in raw]


def load_beat_cards(config: ReferenceLibraryConfig | None = None) -> list[BeatCard]:
    """Load all beat cards from beat_cards.json or custom path."""
    if config and config.beat_cards_file:
        cards_path = Path(config.beat_cards_file)
    else:
        cards_path = references_dir() / "beat_cards.json"

    if not cards_path.exists():
        return []

    raw = json.loads(cards_path.read_text(encoding="utf-8"))
    return [BeatCard.model_validate(item) for item in raw]


def load_reference_library(config: ReferenceLibraryConfig | None = None) -> ReferenceLibrary:
    """Load complete reference library with refs and beat cards."""
    return ReferenceLibrary(
        refs=load_refs(config),
        beat_cards=load_beat_cards(config),
    )


def load_reference_pack(pack_path: Path | str) -> ReferencePack:
    """Load a per-run reference pack from JSON file."""
    path = Path(pack_path)
    if not path.exists():
        raise FileNotFoundError(f"Reference pack not found: {path}")

    raw = json.loads(path.read_text(encoding="utf-8"))
    return ReferencePack.model_validate(raw)


def load_reference_pack_template() -> ReferencePack:
    """Load the default reference pack template."""
    # Try embedded resources first, then external references dir
    embedded_path = Path(__file__).parent / "resources" / "references" / "reference_pack_template.json"
    if embedded_path.exists():
        return load_reference_pack(embedded_path)
    template_path = references_dir() / "reference_pack_template.json"
    return load_reference_pack(template_path)


def get_anti_refs(refs: list[Reference]) -> list[Reference]:
    """Extract anti-references (R023-R026) from the library."""
    anti_ref_ids = {"R023", "R024", "R025", "R026"}
    return [r for r in refs if r.ref_id in anti_ref_ids]


def get_positive_refs(refs: list[Reference]) -> list[Reference]:
    """Get only positive references (excluding anti-refs)."""
    anti_ref_ids = {"R023", "R024", "R025", "R026"}
    return [r for r in refs if r.ref_id not in anti_ref_ids]


def get_refs_for_beat(
    beat_id: str,
    refs: list[Reference],
    beat_cards: list[BeatCard],
) -> list[Reference]:
    """Find all references associated with a specific beat card."""
    # Find the beat card
    beat = next((b for b in beat_cards if b.beat_id == beat_id), None)
    if not beat:
        return []

    # Get refs by example_refs
    ref_ids = set(beat.example_refs)
    return [r for r in refs if r.ref_id in ref_ids]


def get_refs_by_hook_type(refs: list[Reference], hook_type: str) -> list[Reference]:
    """Filter refs by hook_type."""
    return [r for r in refs if r.hook_type == hook_type]


def get_refs_by_tension_tool(refs: list[Reference], tension_tool: str) -> list[Reference]:
    """Filter refs by tension_tool."""
    return [r for r in refs if r.tension_tool == tension_tool]


def get_refs_by_visual_function(refs: list[Reference], visual_function: str) -> list[Reference]:
    """Filter refs by visual_function."""
    return [r for r in refs if r.visual_function == visual_function]


def get_refs_by_feasibility(
    refs: list[Reference],
    feasibility: str,
) -> list[Reference]:
    """Filter refs by AI feasibility level."""
    return [r for r in refs if r.constraints.ai_feasibility == feasibility]


def build_negative_prompt_block(anti_refs: list[Reference]) -> str:
    """Build a NEGATIVE prompt block from anti-references."""
    if not anti_refs:
        return ""

    negative_items: list[str] = []
    for ref in anti_refs:
        # Use prompt_texture_snippets which already have NEGATIVE: prefix
        for snippet in ref.prompt_texture_snippets:
            if snippet.startswith("NEGATIVE:"):
                negative_items.append(snippet.replace("NEGATIVE:", "").strip())
            else:
                negative_items.append(snippet)

    return "NEGATIVE: " + ", ".join(negative_items)


def build_texture_guidance(refs: list[Reference]) -> str:
    """Build texture guidance from selected references."""
    if not refs:
        return ""

    lines: list[str] = []
    for ref in refs:
        lines.append(f"## {ref.ref_id}: {ref.short_description}")
        if ref.texture_cues:
            lines.append(f"**Texture:** {', '.join(ref.texture_cues)}")
        if ref.camera_cues:
            lines.append(f"**Camera:** {', '.join(ref.camera_cues)}")
        if ref.prompt_texture_snippets:
            lines.append(f"**Snippets:** {'; '.join(ref.prompt_texture_snippets)}")
        if ref.do_not_copy_notes:
            lines.append(f"**Avoid:** {ref.do_not_copy_notes}")
        lines.append("")

    return "\n".join(lines)


def build_beat_guidance(beat_cards: list[BeatCard]) -> str:
    """Build narrative beat guidance for agents."""
    if not beat_cards:
        return ""

    lines: list[str] = []
    for beat in beat_cards:
        lines.append(f"## {beat.beat_id}: {beat.name}")
        lines.append(f"**Function:** {beat.narrative_function}")
        lines.append(f"**Setup:** {beat.setup_pattern}")
        lines.append(f"**Payoff:** {beat.payoff_pattern}")
        if beat.common_failure_modes:
            lines.append(f"**Avoid:** {', '.join(beat.common_failure_modes)}")
        if beat.example_refs:
            lines.append(f"**Refs:** {', '.join(beat.example_refs)}")
        lines.append("")

    return "\n".join(lines)


def build_reference_context_for_role(
    role: str,
    library: ReferenceLibrary,
    pack: ReferencePack | None = None,
) -> str:
    """Build role-specific reference context for prompt injection."""
    refs = library.refs
    beat_cards = library.beat_cards
    anti_refs = get_anti_refs(refs)
    positive_refs = get_positive_refs(refs)

    sections: list[str] = []

    # Add aesthetic envelope if we have a pack
    if pack:
        sections.append("# Aesthetic Envelope")
        sections.append(pack.aesthetic_envelope)
        sections.append("")

    # Role-specific content
    if role == "showrunner":
        # Showrunner needs beat cards for narrative structure
        sections.append("# Narrative Beat Patterns")
        sections.append(build_beat_guidance(beat_cards))

    elif role == "dance_mapping":
        # Dance mapping needs texture/camera cues
        sections.append("# Visual Reference Patterns")
        # Show only high/medium feasibility refs
        feasible_refs = [r for r in positive_refs if r.constraints.ai_feasibility != "low"]
        sections.append(build_texture_guidance(feasible_refs[:10]))  # Top 10

    elif role == "cinematography":
        # Cinematography needs full ref details
        sections.append("# Cinematography References")
        sections.append(build_texture_guidance(positive_refs))

    # Anti-references for all roles
    if anti_refs:
        sections.append("# Anti-References (Exclude These)")
        negative_block = build_negative_prompt_block(anti_refs)
        sections.append(negative_block)
        sections.append("")
        sections.append("Use anti-refs as NEGATIVE prompt blocks to prevent style drift.")

    return "\n\n".join(sections)
