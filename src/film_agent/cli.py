"""Command line interface."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from film_agent.automation import auto_run_sdk_loop
from film_agent.io.package_export import package_iteration
from film_agent.prompt_packets import build_all_prompt_packets, build_prompt_packet
from film_agent.prompts import get_prompt_stack, get_role_pack, list_agents
from film_agent.replay_inputs import replay_inputs_for_run
from film_agent.render_api import render_run_via_api
from film_agent.reporting import build_final_report
from film_agent.roles import RoleId, list_roles
from film_agent.state_machine.orchestrator import (
    command_result_payload,
    create_run,
    run_gate0,
    submit_agent,
    validate_gate,
)
from film_agent.vimax_bridge import prepare_vimax_inputs
from film_agent.vimax_pipeline import run_vimax_pipeline

app = typer.Typer(help="Film-Agent manual pipeline CLI", add_completion=False)
role_app = typer.Typer(help="Role pack commands", add_completion=False)
packet_app = typer.Typer(help="Prompt packet commands", add_completion=False)
app.add_typer(role_app, name="role")
app.add_typer(packet_app, name="packet")


def _base_dir() -> Path:
    return Path.cwd()


def _emit(payload: dict) -> None:
    typer.echo(json.dumps(payload, indent=2, ensure_ascii=True))


@app.command("new-run")
def new_run(config: Path = typer.Option(..., "--config", help="Path to YAML config")) -> None:
    result = create_run(_base_dir(), config.resolve())
    _emit(command_result_payload(result))


@app.command("gate0")
def gate0(run_id: str = typer.Option(..., "--run-id", help="Run ID")) -> None:
    result = run_gate0(_base_dir(), run_id)
    _emit(command_result_payload(result))


@app.command("submit")
def submit(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    agent: str = typer.Option(..., "--agent", help="Agent name"),
    file: Path = typer.Option(..., "--file", help="Path to JSON artifact"),
) -> None:
    result = submit_agent(_base_dir(), run_id, agent, file.resolve())
    _emit(command_result_payload(result))


@app.command("validate")
def validate(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    gate: int = typer.Option(..., "--gate", help="Gate number: 1,2,3,4"),
) -> None:
    result = validate_gate(_base_dir(), run_id, gate)
    _emit(command_result_payload(result))


@app.command("package-iteration")
def package_iteration_cmd(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    iteration: int | None = typer.Option(None, "--iter", help="Iteration number; default current"),
) -> None:
    out = package_iteration(_base_dir(), run_id, iteration)
    _emit({"run_id": run_id, "export_path": str(out)})


@app.command("final-report")
def final_report(run_id: str = typer.Option(..., "--run-id", help="Run ID")) -> None:
    out = build_final_report(_base_dir(), run_id)
    _emit({"run_id": run_id, "report": str(out)})


@app.command("show-prompt")
def show_prompt(
    agent: str = typer.Option(
        ...,
        "--agent",
        help=f"Agent name ({', '.join(list_agents())})",
    )
) -> None:
    try:
        typer.echo(get_prompt_stack(agent))
    except Exception as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(code=1)


@app.command("auto-run")
def auto_run(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    model: str = typer.Option("gpt-4.1", "--model", help="OpenAI model for role generation"),
    evaluator_model: str | None = typer.Option(
        None,
        "--evaluator-model",
        help="Optional model for evaluator/judge passes (defaults to --model).",
    ),
    max_cycles: int = typer.Option(20, "--max-cycles", help="Maximum automation cycles"),
    until: str = typer.Option("gate2", "--until", help="Target stage: gate1|gate2|complete"),
    self_eval_rounds: int = typer.Option(2, "--self-eval-rounds", help="Evaluator refine rounds per role output"),
    max_stuck_cycles: int = typer.Option(
        3,
        "--max-stuck-cycles",
        help="Stop early if state does not change for this many cycles.",
    ),
    rate_limit_retries: int = typer.Option(
        5,
        "--rate-limit-retries",
        help="Retries for OpenAI 429 responses with exponential backoff.",
    ),
) -> None:
    try:
        result = auto_run_sdk_loop(
            _base_dir(),
            run_id,
            model=model,
            evaluator_model=evaluator_model,
            max_cycles=max_cycles,
            until=until,
            self_eval_rounds=self_eval_rounds,
            max_stuck_cycles=max_stuck_cycles,
            rate_limit_retries=rate_limit_retries,
        )
    except Exception as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(code=1)
    _emit(result)


@app.command("replay-inputs")
def replay_inputs(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    inputs_dir: Path | None = typer.Option(
        None,
        "--inputs-dir",
        help="Optional explicit directory with authoritative input JSON files.",
    ),
    prefer_current: bool = typer.Option(
        True,
        "--prefer-current/--prefer-base",
        help="Prefer *.current.json variants when duplicate inputs exist.",
    ),
    warn_only_missing: bool = typer.Option(
        True,
        "--warn-only-missing/--error-on-missing",
        help="Warn instead of raising when an expected input file is missing.",
    ),
    stop_on_missing: bool = typer.Option(
        True,
        "--stop-on-missing/--continue-on-missing",
        help="Stop replay on first missing input (default) or continue scanning.",
    ),
) -> None:
    try:
        result = replay_inputs_for_run(
            _base_dir(),
            run_id,
            inputs_dir=inputs_dir.resolve() if inputs_dir else None,
            prefer_current=prefer_current,
            warn_only_missing=warn_only_missing,
            stop_on_missing=stop_on_missing,
        )
    except Exception as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(code=1)
    _emit(result)


@app.command("render-api")
def render_api(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        envvar="YUNWU_API_KEY",
        help="Yunwu API key (or set YUNWU_API_KEY).",
    ),
    provider: str | None = typer.Option(
        None,
        "--provider",
        help="Render provider override (default: render_package.video_provider).",
    ),
    model: str | None = typer.Option(
        None,
        "--model",
        help="Model override (default: render_package.model_version or veo3.1-fast).",
    ),
    out_dir: Path | None = typer.Option(
        None,
        "--out-dir",
        help="Optional output directory for generated shot videos and manifest.",
    ),
    lines_path: Path | None = typer.Option(
        None,
        "--lines-path",
        help="Optional path to vimax_lines.json (defaults to current iteration vimax_input).",
    ),
    poll_interval_s: float = typer.Option(2.0, "--poll-interval", help="Task status polling interval in seconds."),
    timeout_s: float = typer.Option(900.0, "--timeout", help="Per-shot timeout in seconds."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Build requests and manifest without API calls."),
    shot_retry_limit: int = typer.Option(2, "--shot-retry-limit", help="Technical retry limit per shot."),
    fail_fast: bool = typer.Option(
        False,
        "--fail-fast/--best-effort",
        help="Stop on first failed shot (default) or continue collecting failures.",
    ),
) -> None:
    if not dry_run and not (api_key or "").strip():
        _emit({"error": "Missing api key. Set --api-key or YUNWU_API_KEY."})
        raise typer.Exit(code=1)
    try:
        result = render_run_via_api(
            _base_dir(),
            run_id,
            api_key=(api_key or "").strip(),
            provider=provider,
            model=model,
            output_dir=out_dir.resolve() if out_dir else None,
            lines_path=lines_path.resolve() if lines_path else None,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
            dry_run=dry_run,
            fail_fast=fail_fast,
            shot_retry_limit=shot_retry_limit,
        )
    except Exception as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(code=1)

    _emit(
        {
            "run_id": result.run_id,
            "iteration": result.iteration,
            "provider": result.provider,
            "output_dir": str(result.output_dir),
            "manifest": str(result.manifest_path),
            "generated_count": result.generated_count,
            "failed_count": result.failed_count,
        }
    )


@app.command("prepare-vimax")
def prepare_vimax(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    api_key: str | None = typer.Option(
        None,
        "--api-key",
        envvar="OPENAI_API_KEY",
        help="OpenAI API key for reference image generation (or set OPENAI_API_KEY).",
    ),
    image_model: str = typer.Option("gpt-image-1", "--image-model", help="Image model for references."),
    image_size: str | None = typer.Option(
        None,
        "--image-size",
        help="Optional image size override (e.g. 1536x1024).",
    ),
    out_dir: Path | None = typer.Option(
        None,
        "--out-dir",
        help="Optional output directory for ViMax package.",
    ),
    anchor_images: list[Path] = typer.Option(
        [],
        "--anchor-image",
        help="Anchor image path. Provide 5 images for style/identity consistency.",
    ),
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help="Build ViMax line package without generating images.",
    ),
    force_regenerate: bool = typer.Option(
        False,
        "--force-regenerate",
        help="Regenerate references even if files already exist.",
    ),
) -> None:
    if not dry_run and not (api_key or "").strip():
        _emit({"error": "Missing api key. Set --api-key or OPENAI_API_KEY."})
        raise typer.Exit(code=1)

    try:
        result = prepare_vimax_inputs(
            _base_dir(),
            run_id,
            api_key=(api_key or "").strip(),
            image_model=image_model,
            image_size=image_size,
            output_dir=out_dir.resolve() if out_dir else None,
            dry_run=dry_run,
            force_regenerate=force_regenerate,
            anchor_images=[str(item.resolve()) for item in anchor_images] if anchor_images else None,
            required_anchor_count=5,
        )
    except Exception as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(code=1)

    _emit(
        {
            "run_id": result.run_id,
            "iteration": result.iteration,
            "output_dir": str(result.output_dir),
            "references_dir": str(result.references_dir),
            "lines_path": str(result.lines_path),
            "manifest": str(result.manifest_path),
            "planned_lines": result.planned_lines,
            "generated_references": result.generated_references,
            "reused_references": result.reused_references,
            "anchor_count": result.anchor_count,
        }
    )


@app.command("vimax-run")
def vimax_run(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    openai_api_key: str | None = typer.Option(
        None,
        "--openai-api-key",
        envvar="OPENAI_API_KEY",
        help="OpenAI API key for reference generation, QC and TTS.",
    ),
    yunwu_api_key: str | None = typer.Option(
        None,
        "--yunwu-api-key",
        envvar="YUNWU_API_KEY",
        help="Yunwu API key for video generation.",
    ),
    anchor_images: list[Path] = typer.Option(
        [],
        "--anchor-image",
        help="Anchor image path. Provide exactly 5 images.",
    ),
    image_model: str = typer.Option("gpt-image-1", "--image-model", help="Image model for references."),
    qc_model: str = typer.Option("gpt-4.1-mini", "--qc-model", help="VLM judge model."),
    qc_threshold: float = typer.Option(0.75, "--qc-threshold", help="QC acceptance threshold in [0,1]."),
    shot_retry_limit: int = typer.Option(2, "--shot-retry-limit", help="Retry limit per shot."),
    poll_interval_s: float = typer.Option(2.0, "--poll-interval", help="Render poll interval (seconds)."),
    timeout_s: float = typer.Option(900.0, "--timeout", help="Per-shot render timeout (seconds)."),
    tts_model: str = typer.Option("gpt-4o-mini-tts", "--tts-model", help="TTS model for final mix."),
    tts_voice: str = typer.Option("alloy", "--tts-voice", help="TTS voice for final mix."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Run orchestration without external generation calls."),
) -> None:
    if not (openai_api_key or "").strip():
        _emit({"error": "Missing OpenAI API key. Set --openai-api-key or OPENAI_API_KEY."})
        raise typer.Exit(code=1)
    if not (yunwu_api_key or "").strip():
        _emit({"error": "Missing Yunwu API key. Set --yunwu-api-key or YUNWU_API_KEY."})
        raise typer.Exit(code=1)

    try:
        result = run_vimax_pipeline(
            _base_dir(),
            run_id,
            openai_api_key=(openai_api_key or "").strip(),
            yunwu_api_key=(yunwu_api_key or "").strip(),
            anchor_images=[str(item.resolve()) for item in anchor_images],
            image_model=image_model,
            qc_model=qc_model,
            qc_threshold=qc_threshold,
            shot_retry_limit=shot_retry_limit,
            poll_interval_s=poll_interval_s,
            timeout_s=timeout_s,
            tts_model=tts_model,
            tts_voice=tts_voice,
            dry_run=dry_run,
        )
    except Exception as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(code=1)

    _emit(
        {
            "run_id": result.run_id,
            "iteration": result.iteration,
            "vimax_input_dir": str(result.vimax_input_dir),
            "render_manifest": str(result.render_manifest_path),
            "render_qc": str(result.render_qc_path),
            "final_video": str(result.final_video_path),
            "final_mix_manifest": str(result.final_mix_manifest_path),
            "failed_shots": result.failed_shots,
        }
    )


@role_app.command("list")
def role_list() -> None:
    _emit({"roles": [role.value for role in list_roles()]})


@role_app.command("show")
def role_show(
    role: str = typer.Option(..., "--role", help=f"Role name ({', '.join(item.value for item in list_roles())})")
) -> None:
    try:
        pack = get_role_pack(role)
        prompt_stack = get_prompt_stack(role if role != "qa_judge" else "qa_judge")
    except Exception as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(code=1)
    _emit({"role": role, "pack": pack, "prompt_stack": prompt_stack})


@packet_app.command("build")
def packet_build(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    role: str = typer.Option(..., "--role", help=f"Role name ({', '.join(item.value for item in list_roles())})"),
    iteration: int | None = typer.Option(None, "--iter", help="Iteration number; default current"),
) -> None:
    try:
        path, manifest = build_prompt_packet(_base_dir(), run_id, RoleId(role), iteration=iteration)
    except Exception as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(code=1)
    _emit({"run_id": run_id, "role": role, "packet": str(path), "manifest": str(manifest)})


@packet_app.command("build-all")
def packet_build_all(
    run_id: str = typer.Option(..., "--run-id", help="Run ID"),
    iteration: int | None = typer.Option(None, "--iter", help="Iteration number; default current"),
) -> None:
    try:
        outputs = build_all_prompt_packets(_base_dir(), run_id, iteration=iteration)
    except Exception as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(code=1)
    payload = [{"packet": str(packet), "manifest": str(manifest)} for packet, manifest in outputs]
    _emit({"run_id": run_id, "outputs": payload})


def main() -> None:
    app()


if __name__ == "__main__":
    main()
