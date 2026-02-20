"""Prompt packet builder and linting."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from pathlib import Path
from typing import Any

from film_agent.config import load_config
from film_agent.io.hashing import sha256_json
from film_agent.io.json_io import dump_canonical_json, load_json
from film_agent.prompts import get_prompt_stack
from film_agent.resource_locator import find_resource_dir
from film_agent.roles import ROLE_PACKS, RoleId
from film_agent.schemas.registry import AGENT_ARTIFACTS
from film_agent.state_machine.state_store import iteration_key, load_state, run_dir


@dataclass(frozen=True)
class PromptPacketManifest:
    run_id: str
    iteration: int
    role: str
    source_artifacts: list[str]
    output_path: str
    sha256: str


def build_prompt_packet(base_dir: Path, run_id: str, role: RoleId, iteration: int | None = None) -> tuple[Path, Path]:
    run_path = run_dir(base_dir, run_id)
    state = load_state(run_path)
    config = load_config(Path(state.config_path))

    target_iteration = iteration or state.current_iteration
    iter_key = iteration_key(target_iteration)
    packet_dir = run_path / "iterations" / iter_key / "prompt_packets"
    packet_dir.mkdir(parents=True, exist_ok=True)

    manifest = ROLE_PACKS[role]
    missing = _missing_inputs(state, target_iteration, manifest.required_inputs)
    if missing:
        missing_str = ", ".join(missing)
        raise ValueError(f"Cannot build packet for role '{role.value}'. Missing inputs: {missing_str}")

    source_payloads = _collect_inputs(run_path, state, target_iteration, manifest.required_inputs)
    schema_text = _load_schema_text(base_dir, manifest.output_schema)
    prompt = _compose_prompt(
        role=role,
        role_prompt=get_prompt_stack(role.value if role != RoleId.QA_JUDGE else "qa_judge"),
        project_constraints={
            "duration_target_s": config.duration_target_s,
            "core_concepts": config.core_concepts,
            "thresholds": config.thresholds.model_dump(mode="json"),
        },
        source_payloads=source_payloads,
        output_schema=schema_text,
    )

    lint_errors = lint_prompt_packet(prompt, role)
    if lint_errors:
        message = "; ".join(lint_errors)
        raise ValueError(f"Prompt lint failed for role '{role.value}': {message}")

    out_path = packet_dir / f"{role.value}.md"
    out_path.write_text(prompt, encoding="utf-8")

    hash_val = sha256_json({"prompt": prompt})
    manifest_obj = PromptPacketManifest(
        run_id=run_id,
        iteration=target_iteration,
        role=role.value,
        source_artifacts=sorted(source_payloads.keys()),
        output_path=str(out_path),
        sha256=hash_val,
    )
    manifest_path = packet_dir / f"{role.value}.manifest.json"
    dump_canonical_json(manifest_path, asdict(manifest_obj))
    return out_path, manifest_path


def build_all_prompt_packets(base_dir: Path, run_id: str, iteration: int | None = None) -> list[tuple[Path, Path]]:
    outputs: list[tuple[Path, Path]] = []
    for role in (RoleId.SHOWRUNNER, RoleId.DIRECTION, RoleId.DANCE_MAPPING, RoleId.CINEMATOGRAPHY, RoleId.AUDIO, RoleId.QA_JUDGE):
        try:
            outputs.append(build_prompt_packet(base_dir, run_id, role, iteration=iteration))
        except ValueError:
            # Skip roles that cannot be built yet because inputs are not available.
            continue
    return outputs


def lint_prompt_packet(prompt: str, role: RoleId) -> list[str]:
    errors: list[str] = []
    lower = prompt.lower()

    if "json only" not in lower:
        errors.append("missing 'JSON only' directive")
    for section in ("## System", "## Project Constraints", "## Iteration Context", "## Output Contract"):
        if section not in prompt:
            errors.append(f"missing section {section}")

    if role == RoleId.SHOWRUNNER:
        for token in ("5-second", "one primary action", "close-up", "adjacent shots"):
            if token not in lower:
                errors.append(f"missing shot rule token '{token}'")

    if role == RoleId.CINEMATOGRAPHY:
        for token in ("5-second", "one primary action", "continuity", "close-up"):
            if token not in lower:
                errors.append(f"missing shot rule token '{token}'")

    return errors


def _missing_inputs(state, iteration: int, required_inputs: tuple[str, ...]) -> list[str]:
    key = iteration_key(iteration)
    record = state.iterations.get(key)
    if not record:
        return list(required_inputs)
    return [name for name in required_inputs if name not in record.artifacts]


def _collect_inputs(run_path: Path, state, iteration: int, required_inputs: tuple[str, ...]) -> dict[str, Any]:
    key = iteration_key(iteration)
    record = state.iterations.get(key)
    payloads: dict[str, Any] = {}
    if not record:
        return payloads

    for name in required_inputs:
        item = record.artifacts.get(name)
        if not item:
            continue
        payloads[name] = load_json(Path(item.path))

    # Include latest gate reports for QA role context.
    for gate in ("gate0", "gate1", "gate2", "gate3", "gate4"):
        report_path = run_path / "gate_reports" / f"{gate}.{key}.json"
        if report_path.exists():
            payloads[f"{gate}_report"] = load_json(report_path)
    return payloads


def _load_schema_text(base_dir: Path, relative_schema_path: str) -> str:
    direct = base_dir / relative_schema_path
    if direct.exists():
        return direct.read_text(encoding="utf-8")

    schema_name = Path(relative_schema_path).name
    try:
        fallback = find_resource_dir("schemas") / schema_name
    except FileNotFoundError:
        return "{}"

    if not fallback.exists():
        return "{}"
    return fallback.read_text(encoding="utf-8")


def _compose_prompt(
    role: RoleId,
    role_prompt: str,
    project_constraints: dict[str, Any],
    source_payloads: dict[str, Any],
    output_schema: str,
) -> str:
    source_summary = json.dumps(source_payloads, ensure_ascii=True, indent=2)
    constraints = json.dumps(project_constraints, ensure_ascii=True, indent=2)
    shot_rules = (
        "- Each shot is a 5-second unit.\n"
        "- Each shot must contain one primary action only.\n"
        "- Avoid adjacent shots centered on the same character unless required by story logic.\n"
        "- If text/screen/photo/interface details are important, request close-up framing.\n"
        "- Maintain continuity constraints across adjacent shots.\n"
    )
    return (
        f"## System\n{role_prompt.strip()}\n\n"
        "## Project Constraints\n"
        f"{constraints}\n\n"
        "## Technical Shot Rules\n"
        f"{shot_rules}\n"
        "## Iteration Context\n"
        f"Role: {role.value}\n"
        "You must return valid JSON only. No markdown wrappers.\n\n"
        "## Upstream Artifact Summary\n"
        f"{source_summary}\n\n"
        "## Output Contract\n"
        f"{output_schema}\n"
    )


def schema_template_for_agent(agent: str) -> dict[str, Any]:
    if agent not in AGENT_ARTIFACTS:
        raise ValueError(f"Unknown agent '{agent}'")
    model = AGENT_ARTIFACTS[agent].model
    schema = model.model_json_schema()
    return _template_from_schema(schema, root_schema=schema)


def _template_from_schema(schema: dict[str, Any], root_schema: dict[str, Any]) -> Any:
    if "$ref" in schema:
        target = _resolve_ref(root_schema, schema["$ref"])
        return _template_from_schema(target, root_schema=root_schema)

    schema_type = schema.get("type")
    if schema_type == "object":
        result: dict[str, Any] = {}
        properties = schema.get("properties", {})
        required = schema.get("required", [])
        for key, prop in properties.items():
            if key in required:
                result[key] = _template_from_schema(prop, root_schema=root_schema)
        return result
    if schema_type == "array":
        items = schema.get("items", {})
        return [_template_from_schema(items, root_schema=root_schema)]
    if schema_type == "string":
        return ""
    if schema_type == "number":
        return 0
    if schema_type == "integer":
        return 0
    if schema_type == "boolean":
        return False
    if "enum" in schema and schema["enum"]:
        return schema["enum"][0]
    any_of = schema.get("anyOf")
    if any_of:
        return _template_from_schema(any_of[0], root_schema=root_schema)
    return None


def _resolve_ref(root_schema: dict[str, Any], ref: str) -> dict[str, Any]:
    if not ref.startswith("#/"):
        return {}
    node: Any = root_schema
    for part in ref[2:].split("/"):
        if not isinstance(node, dict):
            return {}
        node = node.get(part)
    if isinstance(node, dict):
        return node
    return {}
