"""Command line interface."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from film_agent.automation import auto_run_sdk_loop
from film_agent.io.package_export import package_iteration
from film_agent.prompt_packets import build_all_prompt_packets, build_prompt_packet
from film_agent.prompts import get_prompt_stack, get_role_pack, list_agents
from film_agent.reporting import build_final_report
from film_agent.roles import RoleId, list_roles
from film_agent.state_machine.orchestrator import (
    command_result_payload,
    create_run,
    run_gate0,
    submit_agent,
    validate_gate,
)

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
    max_cycles: int = typer.Option(20, "--max-cycles", help="Maximum automation cycles"),
    until: str = typer.Option("gate2", "--until", help="Target stage: gate1|gate2|complete"),
    self_eval_rounds: int = typer.Option(2, "--self-eval-rounds", help="Evaluator refine rounds per role output"),
) -> None:
    try:
        result = auto_run_sdk_loop(
            _base_dir(),
            run_id,
            model=model,
            max_cycles=max_cycles,
            until=until,
            self_eval_rounds=self_eval_rounds,
        )
    except Exception as exc:
        _emit({"error": str(exc)})
        raise typer.Exit(code=1)
    _emit(result)


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
