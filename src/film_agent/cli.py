"""Command line interface."""

from __future__ import annotations

import json
from pathlib import Path

import typer

from film_agent.io.package_export import package_iteration
from film_agent.reporting import build_final_report
from film_agent.state_machine.orchestrator import (
    command_result_payload,
    create_run,
    run_gate0,
    submit_agent,
    validate_gate,
)

app = typer.Typer(help="Film-Agent manual pipeline CLI", add_completion=False)


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


def main() -> None:
    app()


if __name__ == "__main__":
    main()
