"""SDK-based auto-iteration loop for role prompts."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import re
import time
from typing import Any, Protocol

logger = logging.getLogger(__name__)


class LLMClient(Protocol):
    """Protocol for LLM client abstraction."""
    def create_completion(self, model: str, messages: list[dict[str, str]]) -> tuple[str, Any]:
        """Create a completion. Returns (text, usage)."""
        ...


class OpenAIClient:
    """OpenAI API client wrapper."""
    def __init__(self, api_key: str):
        from openai import OpenAI
        self._client = OpenAI(api_key=api_key)

    def create_completion(self, model: str, messages: list[dict[str, str]]) -> tuple[str, Any]:
        response = self._client.responses.create(model=model, input=messages)
        text = getattr(response, "output_text", "") or extract_response_text(response)
        usage = getattr(response, "usage", None)
        return text, usage


class AnthropicClient:
    """Anthropic Claude API client wrapper."""
    def __init__(self, api_key: str):
        from anthropic import Anthropic
        self._client = Anthropic(api_key=api_key, timeout=300.0)  # 5 minute timeout

    def create_completion(self, model: str, messages: list[dict[str, str]]) -> tuple[str, Any]:
        # Separate system message from user/assistant messages
        system_content = ""
        chat_messages = []
        for msg in messages:
            if msg["role"] == "system":
                system_content += msg["content"] + "\n"
            else:
                chat_messages.append({"role": msg["role"], "content": msg["content"]})

        # Ensure we have at least one user message
        if not chat_messages:
            chat_messages = [{"role": "user", "content": "Generate the requested JSON."}]

        kwargs = {
            "model": model,
            "max_tokens": 8192,
            "messages": chat_messages,
        }
        if system_content.strip():
            kwargs["system"] = system_content.strip()

        response = self._client.messages.create(**kwargs)
        text = response.content[0].text if response.content else ""
        usage = response.usage
        return text, usage


def create_llm_client(model: str) -> tuple[LLMClient, str]:
    """Create appropriate LLM client based on model name. Returns (client, resolved_model)."""
    if model.startswith("claude"):
        api_key = os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("CLAUDE_API_KEY")
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY or CLAUDE_API_KEY is required for Claude models.")
        return AnthropicClient(api_key), model
    else:
        api_key = os.environ.get("OPENAI_API_KEY") or os.environ.get("OPENAI_SDK")
        if not api_key:
            raise ValueError("OPENAI_API_KEY is required for OpenAI models.")
        return OpenAIClient(api_key), model

from film_agent.constants import RunState
from film_agent.io.hashing import sha256_file
from film_agent.io.json_io import dump_canonical_json
from film_agent.io.package_export import package_iteration
from film_agent.io.response_parsing import extract_json_object, extract_response_text
from film_agent.io.transcript_logger import TranscriptLogger, create_transcript_logger
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
    """Iteratively run role prompts via LLM SDK until target stage is reached."""
    client, resolved_model = create_llm_client(model)
    model = resolved_model
    run_path = run_dir(base_dir, run_id)
    judge_model = evaluator_model or model

    # Create evaluator client if different model family
    if evaluator_model and evaluator_model.startswith("claude") != model.startswith("claude"):
        eval_client, _ = create_llm_client(evaluator_model)
    else:
        eval_client = client

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

            # Initialize transcript logger for this role execution
            transcript = create_transcript_logger(
                run_path=run_path,
                run_id=run_id,
                iteration=state.current_iteration,
                role=role.value,
                generator_model=model,
                evaluator_model=judge_model,
            )
            transcript.set_prompt_packet_hash(sha256_file(prompt_path))

            if role == RoleId.SHOWRUNNER:
                payload = _generate_showrunner_candidate(
                    client,
                    model=model,
                    evaluator_model=judge_model,
                    prompt_text=prompt_text,
                    rate_limit_retries=rate_limit_retries,
                    transcript=transcript,
                )
            else:
                payload = _call_model_for_json(
                    client, model, prompt_text,
                    rate_limit_retries=rate_limit_retries,
                    transcript=transcript,
                )
            if role in {RoleId.DANCE_MAPPING, RoleId.CINEMATOGRAPHY, RoleId.AUDIO}:
                payload = _inject_linked_artifact_ids(state, payload)
            payload, was_approved = _refine_payload_with_evaluators(
                client,
                generator_model=model,
                evaluator_model=judge_model,
                role=role,
                prompt_text=prompt_text,
                payload=payload,
                rounds=self_eval_rounds,
                rate_limit_retries=rate_limit_retries,
                transcript=transcript,
            )

            tmp_dir = run_path / "tmp" / f"iter-{state.current_iteration:02d}"
            tmp_dir.mkdir(parents=True, exist_ok=True)
            tmp_file = tmp_dir / f"{agent}.json"
            dump_canonical_json(tmp_file, payload)

            # Finalize and save transcript
            transcript.set_final_payload(payload, was_approved=was_approved)
            transcript_path = transcript.save()
            logger.info(f"Transcript saved: {transcript_path}")

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
    transcript: TranscriptLogger | None = None,
) -> dict[str, Any]:
    messages = [
        {"role": "system", "content": "Return valid JSON only. No markdown wrappers."},
        {"role": "user", "content": prompt_text},
    ]
    return _call_model_for_json_messages(
        client,
        model,
        messages,
        rate_limit_retries=rate_limit_retries,
        transcript=transcript,
        call_type="generate",
    )


def _call_model_for_json_messages(
    client: LLMClient,
    model: str,
    messages: list[dict[str, str]],
    *,
    rate_limit_retries: int = 5,
    transcript: TranscriptLogger | None = None,
    call_type: str = "generate",
    eval_round: int | None = None,
    review_result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    start_time = time.perf_counter()
    error_msg: str | None = None

    try:
        text, usage = _create_completion_with_backoff(
            client,
            model=model,
            messages=messages,
            max_retries=rate_limit_retries,
        )
    except Exception as e:
        error_msg = str(e)
        if transcript:
            latency_ms = (time.perf_counter() - start_time) * 1000
            if call_type == "generate":
                transcript.record_generation(model, messages, "", latency_ms, error=error_msg)
            elif call_type == "evaluate":
                transcript.record_evaluation(model, messages, "", latency_ms, error=error_msg)
            elif call_type == "revise" and eval_round is not None:
                transcript.record_revision(model, messages, "", latency_ms, eval_round, error=error_msg)
        raise

    latency_ms = (time.perf_counter() - start_time) * 1000

    # Record in transcript
    if transcript:
        if call_type == "generate":
            transcript.record_generation(model, messages, text, latency_ms, usage=usage)
        elif call_type == "evaluate":
            transcript.record_evaluation(model, messages, text, latency_ms, review_result=review_result, usage=usage)
        elif call_type == "revise" and eval_round is not None:
            transcript.record_revision(model, messages, text, latency_ms, eval_round, usage=usage)

    payload = extract_json_object(text)
    if not isinstance(payload, dict):
        raise ValueError("SDK model output is not a JSON object.")
    return payload


def _create_completion_with_backoff(
    client: LLMClient,
    *,
    model: str,
    messages: list[dict[str, str]],
    max_retries: int,
) -> tuple[str, Any]:
    """Create completion with retry logic for rate limits."""
    delay_s = 2.0
    max_delay_s = 45.0
    attempts = max(0, int(max_retries))

    for attempt in range(attempts + 1):
        try:
            return client.create_completion(model, messages)
        except Exception as exc:
            error_type = _classify_api_error(exc)
            if error_type == "insufficient_quota":
                raise RuntimeError(
                    "API quota exhausted (insufficient_quota/billing). "
                    "Stop auto-run, switch key/project, or wait for quota reset."
                ) from exc
            if error_type == "rate_limit" and attempt < attempts:
                retry_after = _extract_retry_after_seconds(exc)
                sleep_s = retry_after if retry_after is not None else delay_s
                logger.warning(
                    f"Rate limit hit, retrying in {sleep_s:.1f}s "
                    f"(attempt {attempt + 1}/{attempts})."
                )
                time.sleep(max(0.1, sleep_s))
                if retry_after is None:
                    delay_s = min(max_delay_s, delay_s * 2.0)
                continue
            raise
    raise RuntimeError("Unreachable rate-limit retry state.")


def _classify_api_error(exc: Exception) -> str:
    """Classify API errors from OpenAI or Anthropic."""
    status_code = _extract_status_code(exc)
    message = str(exc).casefold()

    # Quota errors
    if (
        "insufficient_quota" in message
        or "please check your plan and billing details" in message
        or ("quota" in message and "rate limit" not in message)
        or "credit balance is too low" in message  # Anthropic
    ):
        return "insufficient_quota"

    # Rate limit errors
    if (
        status_code == 429
        or "rate limit" in message
        or "too many requests" in message
        or "rate_limit_error" in message  # Anthropic
    ):
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
    transcript: TranscriptLogger | None = None,
) -> tuple[dict[str, Any], bool]:
    """Refine payload with evaluators. Returns (payload, was_approved)."""
    if rounds <= 0:
        return payload, False

    current = dict(payload)
    was_approved = False
    for round_num in range(1, rounds + 1):
        try:
            review = _evaluate_payload(
                client,
                evaluator_model,
                role=role,
                prompt_text=prompt_text,
                payload=current,
                rate_limit_retries=rate_limit_retries,
                transcript=transcript,
                eval_round=round_num,
            )
        except Exception as e:
            logger.warning(
                f"Evaluation failed for role {role.value} in round {round_num}: {e}. "
                "Returning current payload without further refinement."
            )
            return current, was_approved

        if bool(review.get("approved")):
            logger.debug(f"Payload approved for role {role.value} in round {round_num}")
            was_approved = True
            return current, was_approved

        if not _review_has_issues(review):
            logger.debug(f"No issues found for role {role.value} in round {round_num}")
            return current, was_approved

        try:
            current = _revise_payload(
                client,
                generator_model,
                role=role,
                prompt_text=prompt_text,
                payload=current,
                review=review,
                rate_limit_retries=rate_limit_retries,
                transcript=transcript,
                eval_round=round_num,
            )
            logger.debug(f"Payload revised for role {role.value} in round {round_num}")
        except Exception as e:
            logger.warning(
                f"Revision failed for role {role.value} in round {round_num}: {e}. "
                "Returning current payload."
            )
            return current, was_approved
    return current, was_approved


def _evaluate_payload(
    client,
    model: str,
    role: RoleId,
    prompt_text: str,
    payload: dict[str, Any],
    *,
    rate_limit_retries: int = 5,
    transcript: TranscriptLogger | None = None,
    eval_round: int | None = None,
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
    review_raw = _call_model_for_json_messages(
        client,
        model,
        messages,
        rate_limit_retries=rate_limit_retries,
        transcript=transcript,
        call_type="evaluate",
        eval_round=eval_round,
    )
    review = {
        "approved": bool(review_raw.get("approved", False)),
        "structure_issues": _normalize_issue_list(review_raw.get("structure_issues")),
        "content_issues": _normalize_issue_list(review_raw.get("content_issues")),
        "style_issues": _normalize_issue_list(review_raw.get("style_issues")),
        "fix_instructions": _normalize_issue_list(review_raw.get("fix_instructions")),
    }
    # Update transcript with parsed review result
    if transcript and transcript.entry.evaluation_calls:
        transcript.entry.evaluation_calls[-1].metadata["review_result"] = review
    return review


def _revise_payload(
    client,
    model: str,
    role: RoleId,
    prompt_text: str,
    payload: dict[str, Any],
    review: dict[str, Any],
    *,
    rate_limit_retries: int = 5,
    transcript: TranscriptLogger | None = None,
    eval_round: int | None = None,
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
        transcript=transcript,
        call_type="revise",
        eval_round=eval_round,
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
    transcript: TranscriptLogger | None = None,
) -> dict[str, Any]:
    primary = _call_model_for_json(
        client,
        model,
        prompt_text,
        rate_limit_retries=rate_limit_retries,
        transcript=transcript,
    )
    alternate_messages = [
        {
            "role": "system",
            "content": (
                "Return valid JSON only. No markdown wrappers. "
                "Produce an independent second candidate while preserving anchors and retry constraints."
            ),
        },
        {"role": "user", "content": prompt_text},
    ]
    alternate = _call_model_for_json_messages(
        client,
        model,
        alternate_messages,
        rate_limit_retries=rate_limit_retries,
        transcript=transcript,
        call_type="generate",
    )
    return _select_best_candidate_by_review(
        client,
        evaluator_model=evaluator_model,
        role=RoleId.SHOWRUNNER,
        prompt_text=prompt_text,
        candidates=[primary, alternate],
        rate_limit_retries=rate_limit_retries,
        transcript=transcript,
    )


def _select_best_candidate_by_review(
    client,
    *,
    evaluator_model: str,
    role: RoleId,
    prompt_text: str,
    candidates: list[dict[str, Any]],
    rate_limit_retries: int = 5,
    transcript: TranscriptLogger | None = None,
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
                transcript=transcript,
                eval_round=0,  # Round 0 = candidate selection
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
