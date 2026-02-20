"""Gate 0: model profile eligibility."""

from __future__ import annotations

from film_agent.config import RunConfig
from film_agent.schemas.artifacts import GateReport
from film_agent.state_machine.state_store import RunStateData


def evaluate_gate0(state: RunStateData, config: RunConfig) -> GateReport:
    reasons: list[str] = []
    fixes: list[str] = []

    if not config.model_candidates:
        reasons.append("No model_candidates provided in config.")
        fixes.append("Add at least one candidate with weighted_score/physics/human_fidelity/identity.")
        return GateReport(
            gate="gate0",
            passed=False,
            iteration=state.current_iteration,
            metrics={},
            reasons=reasons,
            fix_instructions=fixes,
        )

    ordered = sorted(config.model_candidates, key=lambda c: c.weighted_score, reverse=True)
    selected = ordered[0]
    floors_ok = (
        selected.physics >= config.thresholds.gate0_physics_floor
        and selected.human_fidelity >= config.thresholds.gate0_human_fidelity_floor
        and selected.identity >= config.thresholds.gate0_identity_floor
    )

    if not floors_ok:
        reasons.append(
            "Top weighted candidate does not meet minimum floors for physics/human fidelity/identity."
        )
        fixes.append("Adjust candidate set or threshold floors before proceeding.")

    return GateReport(
        gate="gate0",
        passed=floors_ok,
        iteration=state.current_iteration,
        metrics={
            "selected_candidate": selected.name,
            "selected_weighted_score": selected.weighted_score,
            "selected_physics": selected.physics,
            "selected_human_fidelity": selected.human_fidelity,
            "selected_identity": selected.identity,
            "physics_floor": config.thresholds.gate0_physics_floor,
            "human_fidelity_floor": config.thresholds.gate0_human_fidelity_floor,
            "identity_floor": config.thresholds.gate0_identity_floor,
        },
        reasons=reasons,
        fix_instructions=fixes,
    )
