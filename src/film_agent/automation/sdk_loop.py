"""SDK-based auto-iteration loop for role prompts."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any

logger = logging.getLogger(__name__)

from film_agent.constants import RunState
from film_agent.io.json_io import dump_canonical_json
from film_agent.io.package_export import package_iteration
from film_agent.io.response_parsing import extract_json_object, extract_response_text
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
    max_stuck_cycles: int = 3,
    rate_limit_retries: int = 5,
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
    previous_state: str | None = None
    stuck_count = 0
    while cycles < max_cycles:
        cycles += 1
        state = load_state(run_path)

        # Detect stuck state (no progress)
        if previous_state == state.current_state:
            stuck_count += 1
            if stuck_count >= max_stuck_cycles:
                logger.warning(
                    f"State '{state.current_state}' unchanged for {stuck_count} cycles. "
                    "Possible infinite loop or blocked gate."
                )
                if state.current_state in STATE_TO_ROLE:
                    raise RuntimeError(
                        f"Auto-run stopped early to avoid quota burn: state '{state.current_state}' "
                        f"did not change for {stuck_count} cycles. "
                        "Inspect gate report/prompt packet and retry."
                    )
        else:
            if previous_state is not None:
                logger.info(f"State transition: {previous_state} -> {state.current_state}")
            stuck_count = 0
        previous_state = state.current_state

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
                payload = _generate_showrunner_candidate(
                    client,
                    model=model,
                    evaluator_model=judge_model,
                    prompt_text=prompt_text,
                    rate_limit_retries=rate_limit_retries,
                )
            else:
                payload = _call_model_for_json(client, model, prompt_text, rate_limit_retries=rate_limit_retries)
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
                rate_limit_retries=rate_limit_retries,
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
        "max_stuck_cycles": max_stuck_cycles,
        "rate_limit_retries": rate_limit_retries,
        "export_dir": str(export_dir),
    }


def _call_model_for_json(
    client,
    model: str,
    prompt_text: str,
    *,
    rate_limit_retries: int = 5,
) -> dict[str, Any]:
    return _call_model_for_json_messages(
        client,
        model,
        [
            {"role": "system", "content": "Return valid JSON only. No markdown wrappers."},
            {"role": "user", "content": prompt_text},
        ],
        rate_limit_retries=rate_limit_retries,
    )


def _call_model_for_json_messages(
    client,
    model: str,
    messages: list[dict[str, str]],
    *,
    rate_limit_retries: int = 5,
) -> dict[str, Any]:
    response = _responses_create_with_backoff(
        client,
        model=model,
        messages=messages,
        max_retries=rate_limit_retries,
    )
    text = getattr(response, "output_text", "") or extract_response_text(response)
    payload = extract_json_object(text)
    if not isinstance(payload, dict):
        raise ValueError("SDK model output is not a JSON object.")
    return payload


def _responses_create_with_backoff(
    client,
    *,
    model: str,
    messages: list[dict[str, str]],
    max_retries: int,
):
    delay_s = 2.0
    max_delay_s = 45.0
    attempts = max(0, int(max_retries))

    for attempt in range(attempts + 1):
        try:
            return client.responses.create(model=model, input=messages)
        except Exception as exc:
            error_type = _classify_openai_error(exc)
            if error_type == "insufficient_quota":
                raise RuntimeError(
                    "OpenAI quota exhausted (insufficient_quota/billing). "
                    "Stop auto-run, switch key/project, or wait for quota reset."
                ) from exc
            if error_type == "rate_limit" and attempt < attempts:
                retry_after = _extract_retry_after_seconds(exc)
                sleep_s = retry_after if retry_after is not None else delay_s
                logger.warning(
                    f"OpenAI rate limit hit, retrying in {sleep_s:.1f}s "
                    f"(attempt {attempt + 1}/{attempts})."
                )
                time.sleep(max(0.1, sleep_s))
                if retry_after is None:
                    delay_s = min(max_delay_s, delay_s * 2.0)
                continue
            raise
    raise RuntimeError("Unreachable rate-limit retry state.")


def _classify_openai_error(exc: Exception) -> str:
    status_code = _extract_status_code(exc)
    message = str(exc).casefold()
    if (
        "insufficient_quota" in message
        or "please check your plan and billing details" in message
        or ("quota" in message and "rate limit" not in message)
    ):
        return "insufficient_quota"
    if status_code == 429 or "rate limit" in message or "too many requests" in message:
        return "rate_limit"
    return "other"


def _extract_status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status
    response = getattr(exc, "response", None)
    response_status = getattr(response, "status_code", None)
    if isinstance(response_status, int):
        return response_status
    return None


def _extract_retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = None
    if hasattr(headers, "get"):
        raw = headers.get("retry-after") or headers.get("Retry-After")
    if raw is None:
        return None
    try:
        value = float(str(raw).strip())
    except Exception:
        return None
    if value <= 0:
        return None
    return value


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
    rate_limit_retries: int = 5,
) -> dict[str, Any]:
    if rounds <= 0:
        return payload

    current = dict(payload)
    for round_num in range(1, rounds + 1):
        try:
            review = _evaluate_payload(
                client,
                evaluator_model,
                role=role,
                prompt_text=prompt_text,
                payload=current,
                rate_limit_retries=rate_limit_retries,
            )
        except Exception as e:
            logger.warning(
                f"Evaluation failed for role {role.value} in round {round_num}: {e}. "
                "Returning current payload without further refinement."
            )
            return current

        if bool(review.get("approved")):
            logger.debug(f"Payload approved for role {role.value} in round {round_num}")
            return current

        if not _review_has_issues(review):
            logger.debug(f"No issues found for role {role.value} in round {round_num}")
            return current

        try:
            current = _revise_payload(
                client,
                generator_model,
                role=role,
                prompt_text=prompt_text,
                payload=current,
                review=review,
                rate_limit_retries=rate_limit_retries,
            )
            logger.debug(f"Payload revised for role {role.value} in round {round_num}")
        except Exception as e:
            logger.warning(
                f"Revision failed for role {role.value} in round {round_num}: {e}. "
                "Returning current payload."
            )
            return current
    return current


def _evaluate_payload(
    client,
    model: str,
    role: RoleId,
    prompt_text: str,
    payload: dict[str, Any],
    *,
    rate_limit_retries: int = 5,
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
    review = _call_model_for_json_messages(
        client,
        model,
        messages,
        rate_limit_retries=rate_limit_retries,
    )
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
    *,
    rate_limit_retries: int = 5,
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
    return _call_model_for_json_messages(
        client,
        model,
        messages,
        rate_limit_retries=rate_limit_retries,
    )


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


def _generate_showrunner_candidate(
    client,
    *,
    model: str,
    evaluator_model: str,
    prompt_text: str,
    rate_limit_retries: int = 5,
) -> dict[str, Any]:
    primary = _call_model_for_json(
        client,
        model,
        prompt_text,
        rate_limit_retries=rate_limit_retries,
    )
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
        rate_limit_retries=rate_limit_retries,
    )
    return _select_best_candidate_by_review(
        client,
        evaluator_model=evaluator_model,
        role=RoleId.SHOWRUNNER,
        prompt_text=prompt_text,
        candidates=[primary, alternate],
        rate_limit_retries=rate_limit_retries,
    )


def _select_best_candidate_by_review(
    client,
    *,
    evaluator_model: str,
    role: RoleId,
    prompt_text: str,
    candidates: list[dict[str, Any]],
    rate_limit_retries: int = 5,
) -> dict[str, Any]:
    if not candidates:
        raise ValueError("No candidates to select from.")

    best_index = 0
    best_score = (10_000, 10_000)
    for idx, candidate in enumerate(candidates):
        try:
            review = _evaluate_payload(
                client,
                evaluator_model,
                role=role,
                prompt_text=prompt_text,
                payload=candidate,
                rate_limit_retries=rate_limit_retries,
            )
        except Exception as e:
            logger.warning(
                f"Candidate {idx} evaluation failed for role {role.value}: {e}. "
                f"{'Using first candidate as fallback.' if idx == 0 else 'Skipping candidate.'}"
            )
            if idx == 0:
                return candidate
            continue
        score = _review_score(review)
        if score < best_score:
            best_score = score
            best_index = idx
    logger.debug(f"Selected candidate {best_index} with score {best_score} for role {role.value}")
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
