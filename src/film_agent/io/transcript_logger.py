"""Full transcript logging for LLM calls - enables debugging and eval analysis."""

from __future__ import annotations

import time
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from film_agent.io.json_io import dump_canonical_json


@dataclass
class LLMCallRecord:
    """Single LLM API call record."""

    call_type: str  # "generate", "evaluate", "revise"
    model: str
    messages: list[dict[str, str]]
    response_text: str
    tokens_prompt: int | None = None
    tokens_completion: int | None = None
    tokens_total: int | None = None
    latency_ms: float = 0.0
    error: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class TranscriptEntry:
    """Full transcript for one agent execution cycle."""

    run_id: str
    iteration: int
    role: str
    timestamp_utc: str
    generator_model: str
    evaluator_model: str
    prompt_packet_hash: str | None = None

    # LLM call records
    generation_calls: list[LLMCallRecord] = field(default_factory=list)
    evaluation_calls: list[LLMCallRecord] = field(default_factory=list)
    revision_calls: list[LLMCallRecord] = field(default_factory=list)

    # Final artifact
    final_payload: dict[str, Any] | None = None
    final_payload_hash: str | None = None

    # Aggregate metrics
    total_tokens: int = 0
    total_latency_ms: float = 0.0
    num_refinement_rounds: int = 0
    was_approved: bool = False

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        data = asdict(self)
        # Convert LLMCallRecord objects to dicts
        data["generation_calls"] = [asdict(c) for c in self.generation_calls]
        data["evaluation_calls"] = [asdict(c) for c in self.evaluation_calls]
        data["revision_calls"] = [asdict(c) for c in self.revision_calls]
        return data


class TranscriptLogger:
    """Accumulates LLM call data and saves full transcripts."""

    def __init__(
        self,
        run_path: Path,
        run_id: str,
        iteration: int,
        role: str,
        generator_model: str,
        evaluator_model: str,
    ):
        self.run_path = run_path
        self.entry = TranscriptEntry(
            run_id=run_id,
            iteration=iteration,
            role=role,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            generator_model=generator_model,
            evaluator_model=evaluator_model,
        )
        self._start_time: float | None = None

    def set_prompt_packet_hash(self, hash_value: str) -> None:
        """Set the hash of the prompt packet used."""
        self.entry.prompt_packet_hash = hash_value

    def record_generation(
        self,
        model: str,
        messages: list[dict[str, str]],
        response_text: str,
        latency_ms: float,
        usage: Any | None = None,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a generation LLM call."""
        tokens = self._extract_usage(usage)
        record = LLMCallRecord(
            call_type="generate",
            model=model,
            messages=messages,
            response_text=response_text,
            tokens_prompt=tokens.get("prompt"),
            tokens_completion=tokens.get("completion"),
            tokens_total=tokens.get("total"),
            latency_ms=latency_ms,
            error=error,
            metadata=metadata or {},
        )
        self.entry.generation_calls.append(record)
        self._update_totals(record)

    def record_evaluation(
        self,
        model: str,
        messages: list[dict[str, str]],
        response_text: str,
        latency_ms: float,
        review_result: dict[str, Any] | None = None,
        usage: Any | None = None,
        error: str | None = None,
    ) -> None:
        """Record an evaluation LLM call."""
        tokens = self._extract_usage(usage)
        record = LLMCallRecord(
            call_type="evaluate",
            model=model,
            messages=messages,
            response_text=response_text,
            tokens_prompt=tokens.get("prompt"),
            tokens_completion=tokens.get("completion"),
            tokens_total=tokens.get("total"),
            latency_ms=latency_ms,
            error=error,
            metadata={"review_result": review_result} if review_result else {},
        )
        self.entry.evaluation_calls.append(record)
        self._update_totals(record)

    def record_revision(
        self,
        model: str,
        messages: list[dict[str, str]],
        response_text: str,
        latency_ms: float,
        round_num: int,
        usage: Any | None = None,
        error: str | None = None,
    ) -> None:
        """Record a revision LLM call."""
        tokens = self._extract_usage(usage)
        record = LLMCallRecord(
            call_type="revise",
            model=model,
            messages=messages,
            response_text=response_text,
            tokens_prompt=tokens.get("prompt"),
            tokens_completion=tokens.get("completion"),
            tokens_total=tokens.get("total"),
            latency_ms=latency_ms,
            error=error,
            metadata={"round": round_num},
        )
        self.entry.revision_calls.append(record)
        self.entry.num_refinement_rounds = max(self.entry.num_refinement_rounds, round_num)
        self._update_totals(record)

    def set_final_payload(
        self,
        payload: dict[str, Any],
        payload_hash: str | None = None,
        was_approved: bool = False,
    ) -> None:
        """Set the final artifact payload."""
        self.entry.final_payload = payload
        self.entry.final_payload_hash = payload_hash
        self.entry.was_approved = was_approved

    def save(self) -> Path:
        """Save transcript to disk and return the file path."""
        transcripts_dir = self.run_path / "transcripts"
        transcripts_dir.mkdir(parents=True, exist_ok=True)

        filename = f"iter-{self.entry.iteration:02d}_{self.entry.role}.json"
        path = transcripts_dir / filename

        dump_canonical_json(path, self.entry.to_dict())
        return path

    def _extract_usage(self, usage: Any) -> dict[str, int | None]:
        """Extract token usage from OpenAI response."""
        if usage is None:
            return {"prompt": None, "completion": None, "total": None}

        prompt = getattr(usage, "input_tokens", None) or getattr(usage, "prompt_tokens", None)
        completion = getattr(usage, "output_tokens", None) or getattr(usage, "completion_tokens", None)
        total = getattr(usage, "total_tokens", None)

        if total is None and prompt is not None and completion is not None:
            total = prompt + completion

        return {"prompt": prompt, "completion": completion, "total": total}

    def _update_totals(self, record: LLMCallRecord) -> None:
        """Update aggregate metrics."""
        if record.tokens_total:
            self.entry.total_tokens += record.tokens_total
        self.entry.total_latency_ms += record.latency_ms


def create_transcript_logger(
    run_path: Path,
    run_id: str,
    iteration: int,
    role: str,
    generator_model: str,
    evaluator_model: str,
) -> TranscriptLogger:
    """Factory function to create a transcript logger."""
    return TranscriptLogger(
        run_path=run_path,
        run_id=run_id,
        iteration=iteration,
        role=role,
        generator_model=generator_model,
        evaluator_model=evaluator_model,
    )


def load_transcript_metrics(run_path: Path, iteration: int, role: str) -> dict[str, Any] | None:
    """Load eval metrics from a saved transcript file.

    Returns dict with keys: total_tokens, total_latency_ms, num_llm_calls,
    num_refinement_rounds, was_approved, transcript_path.
    Returns None if transcript not found.
    """
    transcript_path = run_path / "transcripts" / f"iter-{iteration:02d}_{role}.json"
    if not transcript_path.exists():
        return None

    try:
        import json
        data = json.loads(transcript_path.read_text(encoding="utf-8"))

        num_calls = (
            len(data.get("generation_calls", []))
            + len(data.get("evaluation_calls", []))
            + len(data.get("revision_calls", []))
        )

        return {
            "total_tokens": data.get("total_tokens", 0),
            "total_latency_ms": data.get("total_latency_ms", 0.0),
            "num_llm_calls": num_calls,
            "num_refinement_rounds": data.get("num_refinement_rounds", 0),
            "was_approved": data.get("was_approved", False),
            "transcript_path": str(transcript_path),
        }
    except Exception:
        return None
