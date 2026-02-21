"""Reference library schemas for cinematographic patterns and anti-references."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


# =============================================================================
# Reference Library Schemas
# =============================================================================


class RealWorldAnchor(BaseModel):
    """Real-world film/show anchor for a reference."""

    title: str
    note: str
    source_url: str | None = None


class ReferenceConstraints(BaseModel):
    """AI generation constraints for a reference."""

    hard_parts: list[str] = Field(default_factory=list)
    ai_feasibility: Literal["high", "medium", "low"]


class Reference(BaseModel):
    """Single cinematographic reference entry (R001-R028)."""

    ref_id: str = Field(pattern=r"^R\d{3}$")
    type: Literal["video", "still"]
    short_description: str
    hook_type: str
    reveal_type: str
    tension_tool: str
    visual_function: str
    mood_tags: list[str] = Field(default_factory=list)
    anti_tags: list[str] = Field(default_factory=list)
    why_it_works: str
    constraints: ReferenceConstraints
    do_not_copy_notes: str
    texture_cues: list[str] = Field(default_factory=list)
    camera_cues: list[str] = Field(default_factory=list)
    prompt_texture_snippets: list[str] = Field(default_factory=list)
    real_world_anchor: RealWorldAnchor | None = None


class BeatCard(BaseModel):
    """Narrative beat pattern (B01-B18)."""

    beat_id: str = Field(pattern=r"^B\d{2}$")
    name: str
    narrative_function: str
    setup_pattern: str
    payoff_pattern: str
    common_failure_modes: list[str] = Field(default_factory=list)
    example_refs: list[str] = Field(default_factory=list)  # ref_ids


class SelectedRef(BaseModel):
    """Reference selected for a specific run with guidance."""

    ref_id: str = Field(pattern=r"^R\d{3}$")
    role_in_story: Literal["hook", "escalation", "peak", "ending"]
    mapped_shot_ids: list[str] = Field(default_factory=list)
    guidance: str


class ReferencePack(BaseModel):
    """Per-run reference selection with aesthetic envelope."""

    run_id: str
    aesthetic_envelope: str
    selected_refs: list[SelectedRef] = Field(default_factory=list, max_length=12)
    anti_ref_ids: list[str] = Field(default_factory=list)  # R023-R026
    anti_guidance: str = ""


class ReferenceLibrary(BaseModel):
    """Complete reference library with refs and beat cards."""

    refs: list[Reference] = Field(default_factory=list)
    beat_cards: list[BeatCard] = Field(default_factory=list)


# =============================================================================
# Reference QA Gate Schemas (G1-G6)
# =============================================================================


class RefCoverageCheck(BaseModel):
    """G1 Coverage - library has enough variety of hooks and tension tools."""

    hook_types_count: int = 0
    hook_types: list[str] = Field(default_factory=list)
    tension_tools_count: int = 0
    tension_tools: list[str] = Field(default_factory=list)
    passed: bool = False  # hook_types >= 6 AND tension_tools >= 6
    notes: str = ""


class RefCoherenceCheck(BaseModel):
    """G2 Coherence - single aesthetic envelope, anti-refs block drift."""

    aesthetic_envelope: str = ""
    anti_ref_count: int = 0
    anti_ref_ids: list[str] = Field(default_factory=list)
    passed: bool = False
    notes: str = ""


class RefUtilityCheck(BaseModel):
    """G3 Utility - all refs tied to beat cards + have visual_function."""

    refs_with_beats: int = 0
    refs_without_beats: list[str] = Field(default_factory=list)
    total_refs: int = 0
    coverage_pct: float = 0.0
    passed: bool = False  # 100% coverage
    notes: str = ""


class RefRedundancyCheck(BaseModel):
    """G4 Non-redundancy - <10% near-duplicates by visual_function + mood_tags."""

    near_duplicate_pairs: list[tuple[str, str]] = Field(default_factory=list)
    redundancy_pct: float = 0.0
    passed: bool = False  # < 10%
    notes: str = ""


class RefRenderabilityCheck(BaseModel):
    """G5 Renderability - >=70% high+medium AI feasibility."""

    high_count: int = 0
    medium_count: int = 0
    low_count: int = 0
    total_refs: int = 0
    feasibility_pct: float = 0.0
    low_feasibility_refs: list[str] = Field(default_factory=list)
    passed: bool = False  # >= 70%
    notes: str = ""


class RefPackDisciplineCheck(BaseModel):
    """G6 Per-run discipline - pack <= 12 refs, covers hook+escalation+peak+ending."""

    ref_count: int = 0
    covers_hook: bool = False
    covers_escalation: bool = False
    covers_peak: bool = False
    covers_ending: bool = False
    missing_phases: list[str] = Field(default_factory=list)
    passed: bool = False
    notes: str = ""


class ReferenceQAResult(BaseModel):
    """Complete Reference Library QA evaluation with 6 gates."""

    library_hash: str = ""
    pack_id: str = ""

    # 6 gates
    g1_coverage: RefCoverageCheck = Field(default_factory=RefCoverageCheck)
    g2_coherence: RefCoherenceCheck = Field(default_factory=RefCoherenceCheck)
    g3_utility: RefUtilityCheck = Field(default_factory=RefUtilityCheck)
    g4_redundancy: RefRedundancyCheck = Field(default_factory=RefRedundancyCheck)
    g5_renderability: RefRenderabilityCheck = Field(default_factory=RefRenderabilityCheck)
    g6_pack_discipline: RefPackDisciplineCheck = Field(default_factory=RefPackDisciplineCheck)

    # Aggregate
    gates_passed: int = Field(default=0, ge=0, le=6)
    overall_passed: bool = False
    blocking_issues: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
