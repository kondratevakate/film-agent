"""Iteration export bundle builder (prompt-first default)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from film_agent.io.hashing import sha256_file
from film_agent.io.json_io import dump_canonical_json, load_json
from film_agent.prompt_packets import schema_template_for_agent
from film_agent.schemas.registry import AGENT_ARTIFACTS
from film_agent.state_machine.state_store import iteration_key, load_state, run_dir


def package_iteration(base_dir: Path, run_id: str, iteration: int | None = None) -> Path:
    run_path = run_dir(base_dir, run_id)
    state = load_state(run_path)
    target_iter = iteration or state.current_iteration
    iter_key = iteration_key(target_iter)

    src_artifacts = run_path / "iterations" / iter_key / "artifacts"
    if not src_artifacts.exists():
        raise ValueError(f"Iteration artifacts not found: {src_artifacts}")

    export_dir = run_path / "exports" / iter_key
    if export_dir.exists():
        shutil.rmtree(export_dir)
    export_dir.mkdir(parents=True, exist_ok=True)

    artifacts_out = export_dir / "artifacts"
    shutil.copytree(src_artifacts, artifacts_out)

    _copy_prompt_packets(run_path, export_dir, iter_key)
    _write_submission_templates(export_dir)
    _write_prompt_scripts(export_dir)
    _write_legacy_optional_scripts(export_dir)
    _write_runbook(export_dir)
    _write_readable_index(export_dir)
    _write_hash_manifest(export_dir)
    return export_dir


def _copy_prompt_packets(run_path: Path, export_dir: Path, iter_key: str) -> None:
    src = run_path / "iterations" / iter_key / "prompt_packets"
    dst = export_dir / "prompt_packets"
    if src.exists():
        shutil.copytree(src, dst)
        return
    dst.mkdir(parents=True, exist_ok=True)
    (dst / "README.md").write_text(
        "No prompt packets found for this iteration. Use `film-agent packet build` first.\n",
        encoding="utf-8",
    )


def _write_submission_templates(export_dir: Path) -> None:
    out = export_dir / "submission_templates"
    out.mkdir(parents=True, exist_ok=True)

    for agent, entry in sorted(AGENT_ARTIFACTS.items()):
        template = schema_template_for_agent(agent)
        path = out / entry.filename
        dump_canonical_json(path, template)


def _write_prompt_scripts(export_dir: Path) -> None:
    scripts_out = export_dir / "scripts"
    scripts_out.mkdir(parents=True, exist_ok=True)

    artifacts = export_dir / "artifacts"
    _write_plan_summary_script(scripts_out, artifacts)
    _write_image_prompt_sheet(scripts_out, artifacts)
    _write_sora_prompt_sheet(scripts_out, artifacts)
    _write_elevenlabs_sheet(scripts_out, artifacts)


def _write_plan_summary_script(scripts_out: Path, artifacts: Path) -> None:
    beat_path = artifacts / "beat_bible.json"
    direction_path = artifacts / "user_direction_pack.json"

    lines = ["# Plan Summary", ""]
    if beat_path.exists():
        beat_bible = load_json(beat_path)
        lines.append(f"Concept thesis: {beat_bible.get('concept_thesis', '')}")
        lines.append("")
        lines.append("## Beats")
        for beat in beat_bible.get("beats", []):
            lines.append(
                f"- {beat.get('beat_id')} [{beat.get('start_s')}s-{beat.get('end_s')}s]: "
                f"{beat.get('science_claim')} | metaphor: {beat.get('dance_metaphor')}"
            )
    else:
        lines.append("Beat bible artifact is missing.")

    if direction_path.exists():
        direction = load_json(direction_path)
        lines.extend(
            [
                "",
                "## User Direction",
                f"- Goal: {direction.get('iteration_goal', '')}",
                f"- References: {', '.join(direction.get('style_references', []))}",
                f"- Must include: {', '.join(direction.get('must_include', []))}",
                f"- Avoid: {', '.join(direction.get('avoid', []))}",
                f"- Notes: {direction.get('notes', '')}",
            ]
        )

    (scripts_out / "plan_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _shot_prompt(shot: dict[str, Any]) -> str:
    return (
        f"Shot {shot.get('shot_id')}: "
        f"character={shot.get('character')}; "
        f"action={shot.get('pose_action')}; "
        f"background={shot.get('background')}; "
        f"camera={shot.get('camera')}; "
        f"framing={shot.get('framing')}; "
        f"lighting={shot.get('lighting')}; "
        f"location={shot.get('location')}; "
        f"style={'; '.join(shot.get('style_constraints', []))}"
    )


def _write_image_prompt_sheet(scripts_out: Path, artifacts: Path) -> None:
    shot_path = artifacts / "shot_design_sheets.json"
    lines = ["# Image Prompt Sheet", ""]
    if not shot_path.exists():
        lines.append("Shot design sheets artifact is missing.")
    else:
        data = load_json(shot_path)
        for shot in data.get("shots", []):
            lines.append(f"- {_shot_prompt(shot)}")
    (scripts_out / "images_prompts.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_sora_prompt_sheet(scripts_out: Path, artifacts: Path) -> None:
    shot_path = artifacts / "shot_design_sheets.json"
    lines = ["# Sora Prompt Sheet", "", "Use one prompt per shot in order."]
    if not shot_path.exists():
        lines.append("Shot design sheets artifact is missing.")
    else:
        data = load_json(shot_path)
        for shot in data.get("shots", []):
            lines.append(
                f"\n## {shot.get('shot_id')}\n"
                f"{_shot_prompt(shot)}. Keep action simple and single-action in 5 seconds."
            )
    (scripts_out / "sora_prompts.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_elevenlabs_sheet(scripts_out: Path, artifacts: Path) -> None:
    audio_path = artifacts / "audio_plan.json"
    lines = ["# ElevenLabs Voice Lines", ""]
    if not audio_path.exists():
        lines.append("Audio plan artifact is missing.")
    else:
        data = load_json(audio_path)
        for line in data.get("voice_lines", []):
            lines.append(
                f"- {line.get('line_id')} @ {line.get('timestamp_s')}s | "
                f"speaker={line.get('speaker')} | text={line.get('text')}"
            )
    (scripts_out / "elevenlabs_voice_lines.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_legacy_optional_scripts(export_dir: Path) -> None:
    out = export_dir / "legacy_optional_scripts"
    out.mkdir(parents=True, exist_ok=True)

    note = """# Deprecated Optional Scripts

These scripts are no longer part of the default pipeline.
Use prompt packets and manual submission flow as the primary workflow.

If you still want direct provider API execution, keep custom scripts here.
"""
    (out / "README.md").write_text(note, encoding="utf-8")


def _write_runbook(export_dir: Path) -> None:
    runbook = """# RUNBOOK (Prompt-First)

1. Open `prompt_packets/` and run role prompts in your chat interface.
2. Save role outputs as strict JSON files.
3. Submit with `film-agent submit --run-id <id> --agent <role> --file <json>`.
4. Validate gates with `film-agent validate --run-id <id> --gate <n>`.
5. Use `scripts/plan_summary.md`, `scripts/images_prompts.md`, `scripts/sora_prompts.md`, and
   `scripts/elevenlabs_voice_lines.md` as copy-ready sheets for generation tools.
"""
    (export_dir / "RUNBOOK.md").write_text(runbook, encoding="utf-8")


def _write_readable_index(export_dir: Path) -> None:
    lines = ["# Readable Index", ""]
    for path in sorted(export_dir.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(export_dir)
        lines.append(f"- `{rel}`")
    (export_dir / "readable_index.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_hash_manifest(export_dir: Path) -> None:
    manifest: dict[str, str] = {}
    for path in sorted(export_dir.rglob("*")):
        if path.is_dir():
            continue
        rel = str(path.relative_to(export_dir)).replace("\\", "/")
        if rel == "hash_manifest.json":
            continue
        manifest[rel] = sha256_file(path)
    dump_canonical_json(export_dir / "hash_manifest.json", manifest)
