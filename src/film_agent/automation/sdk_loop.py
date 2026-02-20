"""SDK-based auto-iteration loop for role prompts."""

from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any

from film_agent.constants import RunState
from film_agent.io.json_io import dump_canonical_json
from film_agent.io.package_export import package_iteration
from film_agent.prompt_packets import build_all_prompt_packets, build_prompt_packet
from film_agent.roles import RoleId
from film_agent.state_machine.orchestrator import run_gate0, submit_agent, validate_gate
from film_agent.state_machine.state_store import load_state, run_dir


STATE_TO_ROLE: dict[str, RoleId] = {
    RunState.COLLECT_SHOWRUNNER: RoleId.SHOWRUNNER,
    RunState.COLLECT_DIRECTION: RoleId.DIRECTION,
    RunState.COLLECT_DANCE_MAPPING: RoleId.DANCE_MAPPING,
    RunState.COLLECT_CINEMATOGRAPHY: RoleId.CINEMATOGRAPHY,
    RunState.COLLECT_AUDIO: RoleId.AUDIO,
}

ROLE_TO_AGENT: dict[RoleId, str] = {
    RoleId.SHOWRUNNER: "showrunner",
    RoleId.DIRECTION: "direction",
    RoleId.DANCE_MAPPING: "dance_mapping",
    RoleId.CINEMATOGRAPHY: "cinematography",
    RoleId.AUDIO: "audio",
}


def auto_run_sdk_loop(
    base_dir: Path,
    run_id: str,
    model: str = "gpt-4.1",
    evaluator_model: str | None = None,
    max_cycles: int = 20,
    until: str = "gate2",
    self_eval_rounds: int = 2,
) -> dict[str, Any]:
    """Iteratively run role prompts via OpenAI SDK until target stage is reached."""
    key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_SDK")
    if not key:
        raise ValueError("OPENAI_API_KEY or OPENAI_SDK is required for auto-run.")

    try:
        from openai import OpenAI
    except Exception as exc:  # pragma: no cover - runtime environment dependent
        raise RuntimeError("openai package is required for SDK automation.") from exc

    client = OpenAI(api_key=key)
    run_path = run_dir(base_dir, run_id)
    judge_model = evaluator_model or model

    cycles = 0
    while cycles < max_cycles:
        cycles += 1
        state = load_state(run_path)

        if state.current_state == RunState.GATE0:
            run_gate0(base_dir, run_id)
            continue

        if _target_reached(state.current_state, until):
            break
        if state.current_state in {RunState.FAILED, RunState.COMPLETE}:
            break

        if state.current_state in STATE_TO_ROLE:
            role = STATE_TO_ROLE[state.current_state]
            prompt_path, _manifest_path = build_prompt_packet(base_dir, run_id, role)
            prompt_text = prompt_path.read_text(encoding="utf-8")
            agent = ROLE_TO_AGENT[role]

            if role == RoleId.SHOWRUNNER:
                payload = _generate_showrunner_candidate(client, model=model, evaluator_model=judge_model, prompt_text=prompt_text)
            else:
                payload = _call_model_for_json(client, model, prompt_text)
            if role in {RoleId.DANCE_MAPPING, RoleId.CINEMATOGRAPHY, RoleId.AUDIO}:
                payload = _inject_linked_artifact_ids(state, payload)
            payload = _refine_payload_with_evaluators(
                client,
                generator_model=model,
                evaluator_model=judge_model,
                role=role,
                prompt_text=prompt_text,
                payload=payload,
                rounds=self_eval_rounds,
            )

            tmp_dir = run_path / "tmp" / f"iter-{state.current_iteration:02d}"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_file = tmp_dir / f"{agent}.json"
            dump_canonical_json(tmp_file, payload)
            submit_agent(base_dir, run_id, agent, tmp_file)
            continue

        if state.current_state == RunState.GATE1:
            validate_gate(base_dir, run_id, 1)
            continue
        if state.current_state == RunState.GATE2:
            validate_gate(base_dir, run_id, 2)
            continue
        if state.current_state == RunState.GATE3:
            validate_gate(base_dir, run_id, 3)
            continue

        # For later stages that need external benchmark metrics, stop and export.
        if state.current_state in {RunState.DRYRUN, RunState.FINAL_RENDER, RunState.GATE4}:
            break

        break

    state = load_state(run_path)
    build_all_prompt_packets(base_dir, run_id, iteration=state.current_iteration)
    export_dir = package_iteration(base_dir, run_id, iteration=state.current_iteration)
    return {
        "run_id": run_id,
        "current_state": state.current_state,
        "current_iteration": state.current_iteration,
        "cycles": cycles,
        "generator_model": model,
        "evaluator_model": judge_model,
        "export_dir": str(export_dir),
    }


def _call_model_for_json(client, model: str, prompt_text: str) -> dict[str, Any]:
    return _call_model_for_json_messages(
        client,
        model,
        [
            {"role": "system", "content": "Return valid JSON only. No markdown wrappers."},
            {"role": "user", "content": prompt_text},
        ],
    )


def _call_model_for_json_messages(client, model: str, messages: list[dict[str, str]]) -> dict[str, Any]:
    response = client.responses.create(model=model, input=messages)
    text = getattr(response, "output_text", "") or _extract_response_text(response)
    payload = _extract_json_object(text)
    if not isinstance(payload, dict):
        raise ValueError("SDK model output is not a JSON object.")
    return payload


def _extract_response_text(response: Any) -> str:
    data = response.model_dump() if hasattr(response, "model_dump") else {}
    output = data.get("output", [])
    chunks: list[str] = []
    for item in output:
        for content in item.get("content", []):
            text = content.get("text")
            if text:
                chunks.append(text)
    return "\n".join(chunks)


def _extract_json_object(text: str) -> Any:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\\s*```$", "", cleaned)

    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Try to find first JSON object block.
    decoder = json.JSONDecoder()
    for idx, char in enumerate(cleaned):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(cleaned[idx:])
            return obj
        except json.JSONDecodeError:
            continue
    raise ValueError("Could not parse JSON object from SDK response.")


def _inject_linked_artifact_ids(state, payload: dict[str, Any]) -> dict[str, Any]:
    updated = dict(payload)
    if state.latest_direction_pack_id:
        updated["script_review_id"] = state.latest_direction_pack_id
    if state.latest_image_prompt_package_id:
        updated["image_prompt_package_id"] = state.latest_image_prompt_package_id
    if state.latest_selected_images_id:
        updated["selected_images_id"] = state.latest_selected_images_id
    return updated


def _refine_payload_with_evaluators(
    client,
    generator_model: str,
    evaluator_model: str,
    role: RoleId,
    prompt_text: str,
    payload: dict[str, Any],
    rounds: int,
) -> dict[str, Any]:
    if rounds <= 0:
        return payload

    current = dict(payload)
    for _ in range(rounds):
        try:
            review = _evaluate_payload(client, evaluator_model, role=role, prompt_text=prompt_text, payload=current)
        except Exception:
            return current

        if bool(review.get("approved")):
            return current

        if not _review_has_issues(review):
            return current

        try:
            current = _revise_payload(
                client,
                generator_model,
                role=role,
                prompt_text=prompt_text,
                payload=current,
                review=review,
            )
        except Exception:
            return current
    return current


def _evaluate_payload(
    client,
    model: str,
    role: RoleId,
    prompt_text: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "You are a strict artifact evaluator. Return JSON only with keys: "
                "approved (bool), structure_issues (array), content_issues (array), "
                "style_issues (array), fix_instructions (array)."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Role: {role.value}\n\n"
                "Evaluate this artifact against the prompt packet constraints.\n"
                "Mark approved=true only if no issues remain.\n\n"
                "PROMPT PACKET:\n"
                f"{prompt_text}\n\n"
                "CANDIDATE JSON:\n"
                f"{json.dumps(payload, ensure_ascii=True, indent=2)}"
            ),
        },
    ]
    review = _call_model_for_json_messages(client, model, messages)
    return {
        "approved": bool(review.get("approved", False)),
        "structure_issues": _normalize_issue_list(review.get("structure_issues")),
        "content_issues": _normalize_issue_list(review.get("content_issues")),
        "style_issues": _normalize_issue_list(review.get("style_issues")),
        "fix_instructions": _normalize_issue_list(review.get("fix_instructions")),
    }


def _revise_payload(
    client,
    model: str,
    role: RoleId,
    prompt_text: str,
    payload: dict[str, Any],
    review: dict[str, Any],
) -> dict[str, Any]:
    messages = [
        {
            "role": "system",
            "content": (
                "You revise JSON artifacts. Return JSON only. "
                "Apply feedback while preserving schema validity and linked ids."
            ),
        },
        {
            "role": "user",
            "content": (
                f"Role: {role.value}\n\n"
                "Revise the candidate JSON using the evaluator feedback below.\n"
                "Do not add wrapper text.\n\n"
                "PROMPT PACKET:\n"
                f"{prompt_text}\n\n"
                "CURRENT JSON:\n"
                f"{json.dumps(payload, ensure_ascii=True, indent=2)}\n\n"
                "EVALUATOR FEEDBACK:\n"
                f"{json.dumps(review, ensure_ascii=True, indent=2)}"
            ),
        },
    ]
    return _call_model_for_json_messages(client, model, messages)


def _normalize_issue_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def _review_has_issues(review: dict[str, Any]) -> bool:
    return any(
        review.get(key)
        for key in ("structure_issues", "content_issues", "style_issues", "fix_instructions")
    )


def _generate_showrunner_candidate(client, *, model: str, evaluator_model: str, prompt_text: str) -> dict[str, Any]:
    primary = _call_model_for_json(client, model, prompt_text)
    alternate = _call_model_for_json_messages(
        client,
        model,
        [
            {
                "role": "system",
                "content": (
                    "Return valid JSON only. No markdown wrappers. "
                    "Produce an independent second candidate while preserving anchors and retry constraints."
                ),
            },
            {"role": "user", "content": prompt_text},
        ],
    )
    return _select_best_candidate_by_review(
        client,
        evaluator_model=evaluator_model,
        role=RoleId.SHOWRUNNER,
        prompt_text=prompt_text,
        candidates=[primary, alternate],
    )


def _select_best_candidate_by_review(
    client,
    *,
    evaluator_model: str,
    role: RoleId,
    prompt_text: str,
    candidates: list[dict[str, Any]],
) -> dict[str, Any]:
    if not candidates:
        raise ValueError("No candidates to select from.")

    best_index = 0
    best_score = (10_000, 10_000)
    for idx, candidate in enumerate(candidates):
        try:
            review = _evaluate_payload(client, evaluator_model, role=role, prompt_text=prompt_text, payload=candidate)
        except Exception:
            if idx == 0:
                return candidate
            continue
        score = _review_score(review)
        if score < best_score:
            best_score = score
            best_index = idx
    return candidates[best_index]


def _review_score(review: dict[str, Any]) -> tuple[int, int]:
    approved_penalty = 0 if bool(review.get("approved")) else 1
    issue_count = sum(len(review.get(key, [])) for key in ("structure_issues", "content_issues", "style_issues", "fix_instructions"))
    return (approved_penalty, issue_count)


def _target_reached(current_state: str, until: str) -> bool:
    if until == "gate2":
        return current_state in {
            RunState.COLLECT_DANCE_MAPPING,
            RunState.GATE3,
            RunState.COLLECT_CINEMATOGRAPHY,
            RunState.COLLECT_AUDIO,
            RunState.FINAL_RENDER,
            RunState.GATE4,
            RunState.COMPLETE,
        }
    if until == "gate1":
        return current_state in {
            RunState.COLLECT_DIRECTION,
            RunState.GATE2,
            RunState.COLLECT_DANCE_MAPPING,
            RunState.GATE3,
            RunState.COLLECT_CINEMATOGRAPHY,
            RunState.COLLECT_AUDIO,
            RunState.FINAL_RENDER,
            RunState.GATE4,
            RunState.COMPLETE,
        }
    return current_state == RunState.COMPLETE
