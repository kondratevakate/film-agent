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
    script_path = artifacts / "script.json"
    review_path = artifacts / "script_review.json"

    lines = ["# Plan Summary", ""]
    if script_path.exists():
        script = load_json(script_path)
        lines.append(f"Title: {script.get('title', '')}")
        lines.append(f"Logline: {script.get('logline', '')}")
        lines.append(f"Theme: {script.get('theme', '')}")
        lines.append("")
        lines.append("## Script Lines")
        for line in script.get("lines", []):
            speaker = line.get("speaker") or "-"
            lines.append(
                f"- {line.get('line_id')} ({line.get('kind')}) speaker={speaker} "
                f"duration={line.get('est_duration_s')}s: {line.get('text')}"
            )
    else:
        lines.append("Script artifact is missing.")

    if review_path.exists():
        review = load_json(review_path)
        lines.extend(
            [
                "",
                "## Script Review",
                f"- Version: {review.get('script_version', '')}",
                f"- lock_story_facts: {review.get('lock_story_facts', False)}",
                f"- Approved facts: {', '.join(review.get('approved_story_facts', []))}",
                f"- Character registry: {', '.join(review.get('approved_character_registry', []))}",
                f"- Unresolved: {', '.join(review.get('unresolved_items', []))}",
            ]
        )

    (scripts_out / "plan_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _image_prompt_line(item: dict[str, Any]) -> str:
    return (
        f"Shot {item.get('shot_id')}: intent={item.get('intent')}; "
        f"duration={item.get('duration_s')}s; "
        f"prompt={item.get('image_prompt')}; "
        f"negative={item.get('negative_prompt')}"
    )


def _write_image_prompt_sheet(scripts_out: Path, artifacts: Path) -> None:
    prompt_path = artifacts / "image_prompt_package.json"
    lines = ["# Image Prompt Sheet", ""]
    if not prompt_path.exists():
        lines.append("Image prompt package artifact is missing.")
    else:
        data = load_json(prompt_path)
        lines.append(f"style_anchor: {data.get('style_anchor', '')}")
        lines.append("")
        for item in data.get("image_prompts", []):
            lines.append(f"- {_image_prompt_line(item)}")
    (scripts_out / "images_prompts.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_sora_prompt_sheet(scripts_out: Path, artifacts: Path) -> None:
    av_path = artifacts / "av_prompt_package.json"
    lines = ["# Sora Prompt Sheet", "", "Use one prompt per shot in order."]
    if not av_path.exists():
        lines.append("AV prompt package artifact is missing.")
    else:
        data = load_json(av_path)
        for shot in data.get("shot_prompts", []):
            lines.append(
                f"\n## {shot.get('shot_id')}\n"
                f"{shot.get('video_prompt')}"
            )
    (scripts_out / "sora_prompts.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_elevenlabs_sheet(scripts_out: Path, artifacts: Path) -> None:
    av_path = artifacts / "av_prompt_package.json"
    lines = ["# ElevenLabs Voice Lines", ""]
    if not av_path.exists():
        lines.append("AV prompt package artifact is missing.")
    else:
        data = load_json(av_path)
        for line in data.get("shot_prompts", []):
            if not (line.get("tts_text") or "").strip():
                continue
            lines.append(
                f"- shot={line.get('shot_id')} duration={line.get('duration_s')}s | "
                f"text={line.get('tts_text')}"
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
        rel = path.relative_to(export_dir).as_posix()
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
