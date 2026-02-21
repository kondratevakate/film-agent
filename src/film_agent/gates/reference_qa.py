"""Reference Library QA Gates (G1-G6)."""

from __future__ import annotations

from pathlib import Path

from film_agent.config import RunConfig
from film_agent.reference_library import (
    get_anti_refs,
    load_beat_cards,
    load_reference_pack,
    load_refs,
)
from film_agent.schemas.artifacts import GateReport
from film_agent.schemas.references import (
    BeatCard,
    Reference,
    ReferencePack,
    ReferenceQAResult,
    RefCoverageCheck,
    RefCoherenceCheck,
    RefPackDisciplineCheck,
    RefRedundancyCheck,
    RefRenderabilityCheck,
    RefUtilityCheck,
)
from film_agent.state_machine.state_store import RunStateData


def _check_g1_coverage(refs: list[Reference]) -> RefCoverageCheck:
    """G1 Coverage - library has enough variety of hooks and tension tools.

    Pass criteria: hook_types >= 6 AND tension_tools >= 6
    """
    hook_types = list({r.hook_type for r in refs if r.hook_type})
    tension_tools = list({r.tension_tool for r in refs if r.tension_tool})

    passed = len(hook_types) >= 6 and len(tension_tools) >= 6

    return RefCoverageCheck(
        hook_types_count=len(hook_types),
        hook_types=sorted(hook_types),
        tension_tools_count=len(tension_tools),
        tension_tools=sorted(tension_tools),
        passed=passed,
        notes=f"Found {len(hook_types)} hook types and {len(tension_tools)} tension tools",
    )


def _check_g2_coherence(
    refs: list[Reference],
    pack: ReferencePack | None,
) -> RefCoherenceCheck:
    """G2 Coherence - single aesthetic envelope, anti-refs present.

    Pass criteria: anti-refs exist (R023-R026) and aesthetic envelope defined if pack exists
    """
    anti_refs = get_anti_refs(refs)
    anti_ref_ids = [r.ref_id for r in anti_refs]

    aesthetic_envelope = pack.aesthetic_envelope if pack else ""

    # Pass if we have anti-refs to block drift
    passed = len(anti_refs) >= 4  # R023-R026

    return RefCoherenceCheck(
        aesthetic_envelope=aesthetic_envelope,
        anti_ref_count=len(anti_refs),
        anti_ref_ids=anti_ref_ids,
        passed=passed,
        notes="Anti-refs present to block drift" if passed else "Missing anti-refs R023-R026",
    )


def _check_g3_utility(
    refs: list[Reference],
    beat_cards: list[BeatCard],
) -> RefUtilityCheck:
    """G3 Utility - all refs tied to beat cards + have visual_function.

    Pass criteria: 100% of refs are referenced in at least one beat card's example_refs
    """
    # Get all ref_ids referenced in beat cards
    refs_in_beats: set[str] = set()
    for beat in beat_cards:
        refs_in_beats.update(beat.example_refs)

    # Count refs with beat card links
    refs_with_beats = [r for r in refs if r.ref_id in refs_in_beats]
    refs_without = [r.ref_id for r in refs if r.ref_id not in refs_in_beats]

    total = len(refs)
    coverage_pct = (len(refs_with_beats) / total * 100) if total > 0 else 0

    # Pass if all refs have visual_function (they all do by schema) and are in beat cards
    passed = coverage_pct == 100

    return RefUtilityCheck(
        refs_with_beats=len(refs_with_beats),
        refs_without_beats=refs_without,
        total_refs=total,
        coverage_pct=coverage_pct,
        passed=passed,
        notes=f"{coverage_pct:.1f}% refs linked to beat cards",
    )


def _check_g4_redundancy(refs: list[Reference]) -> RefRedundancyCheck:
    """G4 Non-redundancy - <10% near-duplicates by visual_function + mood_tags.

    Near-duplicates: same visual_function AND >50% mood_tag overlap
    """
    near_duplicates: list[tuple[str, str]] = []

    for i, r1 in enumerate(refs):
        for r2 in refs[i + 1 :]:
            # Same visual_function
            if r1.visual_function != r2.visual_function:
                continue

            # Check mood_tag overlap
            tags1 = set(r1.mood_tags)
            tags2 = set(r2.mood_tags)
            if not tags1 or not tags2:
                continue

            overlap = len(tags1 & tags2)
            min_len = min(len(tags1), len(tags2))
            if min_len > 0 and (overlap / min_len) > 0.5:
                near_duplicates.append((r1.ref_id, r2.ref_id))

    total = len(refs)
    # Count unique refs involved in duplicates
    dup_refs = set()
    for r1, r2 in near_duplicates:
        dup_refs.add(r1)
        dup_refs.add(r2)

    redundancy_pct = (len(dup_refs) / total * 100) if total > 0 else 0
    passed = redundancy_pct < 10

    return RefRedundancyCheck(
        near_duplicate_pairs=near_duplicates,
        redundancy_pct=redundancy_pct,
        passed=passed,
        notes=f"{len(near_duplicates)} near-duplicate pairs ({redundancy_pct:.1f}%)",
    )


def _check_g5_renderability(refs: list[Reference]) -> RefRenderabilityCheck:
    """G5 Renderability - >=70% high+medium AI feasibility.

    Single-frame feasibility check.
    """
    high_refs = [r for r in refs if r.constraints.ai_feasibility == "high"]
    medium_refs = [r for r in refs if r.constraints.ai_feasibility == "medium"]
    low_refs = [r for r in refs if r.constraints.ai_feasibility == "low"]

    total = len(refs)
    feasible_count = len(high_refs) + len(medium_refs)
    feasibility_pct = (feasible_count / total * 100) if total > 0 else 0

    passed = feasibility_pct >= 70

    return RefRenderabilityCheck(
        high_count=len(high_refs),
        medium_count=len(medium_refs),
        low_count=len(low_refs),
        total_refs=total,
        feasibility_pct=feasibility_pct,
        low_feasibility_refs=[r.ref_id for r in low_refs],
        passed=passed,
        notes=f"{feasibility_pct:.1f}% high+medium feasibility ({feasible_count}/{total})",
    )


def _check_g6_pack_discipline(pack: ReferencePack | None) -> RefPackDisciplineCheck:
    """G6 Per-run discipline - pack <= 12 refs, covers hook+escalation+peak+ending."""
    if not pack:
        return RefPackDisciplineCheck(
            ref_count=0,
            covers_hook=False,
            covers_escalation=False,
            covers_peak=False,
            covers_ending=False,
            missing_phases=["hook", "escalation", "peak", "ending"],
            passed=False,
            notes="No reference pack provided",
        )

    ref_count = len(pack.selected_refs)
    roles = {r.role_in_story for r in pack.selected_refs}

    covers_hook = "hook" in roles
    covers_escalation = "escalation" in roles
    covers_peak = "peak" in roles
    covers_ending = "ending" in roles

    missing_phases = []
    if not covers_hook:
        missing_phases.append("hook")
    if not covers_escalation:
        missing_phases.append("escalation")
    if not covers_peak:
        missing_phases.append("peak")
    if not covers_ending:
        missing_phases.append("ending")

    # Pass: <=12 refs AND covers all phases
    passed = ref_count <= 12 and len(missing_phases) == 0

    return RefPackDisciplineCheck(
        ref_count=ref_count,
        covers_hook=covers_hook,
        covers_escalation=covers_escalation,
        covers_peak=covers_peak,
        covers_ending=covers_ending,
        missing_phases=missing_phases,
        passed=passed,
        notes=f"{ref_count} refs selected, missing phases: {missing_phases}" if missing_phases else f"{ref_count} refs covering all phases",
    )


def evaluate_reference_qa(
    run_path: Path,
    state: RunStateData,
    config: RunConfig,
) -> ReferenceQAResult:
    """Run all 6 reference QA gates."""
    # Load reference library
    refs = load_refs(config.reference_library if config.reference_library.enabled else None)
    beat_cards = load_beat_cards(config.reference_library if config.reference_library.enabled else None)

    # Load reference pack if provided
    pack: ReferencePack | None = None
    if config.reference_library.enabled and config.reference_library.reference_pack_file:
        try:
            pack = load_reference_pack(config.reference_library.reference_pack_file)
        except FileNotFoundError:
            pass

    # Run all gates
    g1 = _check_g1_coverage(refs)
    g2 = _check_g2_coherence(refs, pack)
    g3 = _check_g3_utility(refs, beat_cards)
    g4 = _check_g4_redundancy(refs)
    g5 = _check_g5_renderability(refs)
    g6 = _check_g6_pack_discipline(pack)

    # Aggregate
    gates_passed = sum([g1.passed, g2.passed, g3.passed, g4.passed, g5.passed, g6.passed])
    overall_passed = gates_passed == 6

    blocking_issues = []
    recommendations = []

    if not g1.passed:
        blocking_issues.append(f"G1 Coverage: need ≥6 hook_types and tension_tools (found {g1.hook_types_count}, {g1.tension_tools_count})")
    if not g2.passed:
        blocking_issues.append("G2 Coherence: missing anti-refs R023-R026")
    if not g3.passed:
        blocking_issues.append(f"G3 Utility: {g3.coverage_pct:.1f}% refs linked to beat cards (need 100%)")
        recommendations.append(f"Add refs {g3.refs_without_beats} to beat cards")
    if not g4.passed:
        blocking_issues.append(f"G4 Redundancy: {g4.redundancy_pct:.1f}% near-duplicates (need <10%)")
    if not g5.passed:
        blocking_issues.append(f"G5 Renderability: {g5.feasibility_pct:.1f}% feasible (need ≥70%)")
        if g5.low_feasibility_refs:
            recommendations.append(f"Review low-feasibility refs: {g5.low_feasibility_refs}")
    if not g6.passed:
        blocking_issues.append(f"G6 Pack Discipline: missing {g6.missing_phases}")

    return ReferenceQAResult(
        library_hash="",  # Could compute hash of refs.json
        pack_id=pack.run_id if pack else "",
        g1_coverage=g1,
        g2_coherence=g2,
        g3_utility=g3,
        g4_redundancy=g4,
        g5_renderability=g5,
        g6_pack_discipline=g6,
        gates_passed=gates_passed,
        overall_passed=overall_passed,
        blocking_issues=blocking_issues,
        recommendations=recommendations,
    )


def evaluate_reference_qa_standalone() -> ReferenceQAResult:
    """Run reference QA gates without a run context (for CLI validation)."""
    refs = load_refs(None)
    beat_cards = load_beat_cards(None)

    # Load default template pack
    try:
        pack = load_reference_pack(Path(__file__).parent.parent / "resources" / "references" / "reference_pack_template.json")
    except FileNotFoundError:
        pack = None

    g1 = _check_g1_coverage(refs)
    g2 = _check_g2_coherence(refs, pack)
    g3 = _check_g3_utility(refs, beat_cards)
    g4 = _check_g4_redundancy(refs)
    g5 = _check_g5_renderability(refs)
    g6 = _check_g6_pack_discipline(pack)

    gates_passed = sum([g1.passed, g2.passed, g3.passed, g4.passed, g5.passed, g6.passed])

    return ReferenceQAResult(
        g1_coverage=g1,
        g2_coherence=g2,
        g3_utility=g3,
        g4_redundancy=g4,
        g5_renderability=g5,
        g6_pack_discipline=g6,
        gates_passed=gates_passed,
        overall_passed=gates_passed == 6,
        blocking_issues=[],
        recommendations=[],
    )
