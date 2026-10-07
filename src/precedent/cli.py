"""Precedent command line. Each command is filled in by its workstream (see docs/briefs)."""

from __future__ import annotations

import os

import typer
from dotenv import load_dotenv

load_dotenv()
app = typer.Typer(no_args_is_help=True, add_completion=False)


def _todo(ws: str) -> None:
    typer.secho(f"Not built yet. See docs/briefs/{ws}.md", fg=typer.colors.YELLOW)
    raise typer.Exit(code=2)


@app.command()
def world(template: str = "northwind", seed: int = 7) -> None:
    """Generate worlds/<seed>/ from a template (WS1)."""
    from precedent.world.db import world_dir
    from precedent.world.generator import generate

    out = world_dir(seed)
    m = generate(template, seed, out)
    counts = ", ".join(f"{k} {v}" for k, v in m.counts.items() if k != "audit_log")
    typer.echo(f"Generated {template} seed {seed} in {out}: {counts}.")


@app.command()
def apps(seed: int = 7, port: int = 8100) -> None:
    """Serve Mail, Books, Drive and Chat for a seed (WS2)."""
    import uvicorn

    from precedent.apps.server import create_app

    if os.getenv("PRECEDENT_SCENARIO_TOKEN", "change-me") == "change-me":
        typer.secho(
            "Set PRECEDENT_SCENARIO_TOKEN in .env (make setup generates one); "
            "the scenario hooks must not use a guessable token.",
            fg=typer.colors.RED,
        )
        raise typer.Exit(code=2)
    typer.echo(f"Company apps for seed {seed} on http://localhost:{port}/mail/")
    uvicorn.run(create_app(seed), host="127.0.0.1", port=port, log_level="warning")


@app.command()
def run(
    task: str = typer.Option(..., help="Natural-language request"),
    seed: int = 7,
    worker: str = typer.Option("precedent", help="precedent | baseline"),
    resume: bool = typer.Option(False, help="Continue an unfinished run of the same task"),
    headed: bool = False,
) -> None:
    """Run the worker on a request (WS3)."""
    import asyncio

    from precedent.worker.runner import RunConfig
    from precedent.worker.runner import run as run_worker

    cfg = RunConfig(request=task, seed=seed, worker=worker, headed=headed, resume=bool(resume))
    summary = asyncio.run(run_worker(cfg))
    claimed = (summary["claimed"] or {}).get("claimed", "none")
    typer.echo(
        f"Run {summary['run_id']}: outcome {summary['outcome']} (Ava claimed {claimed}), "
        f"{summary['steps']} steps, {summary['tokens_in'] + summary['tokens_out']} tokens, "
        f"{summary['seconds']} s. Events: {summary['dir']}/events.jsonl"
    )
    if summary["error"]:
        typer.secho(f"Error: {summary['error']}", fg=typer.colors.RED)


@app.command()
def grade(seed: int = 7, task: str = "T1_figma", run: str = typer.Option(...)) -> None:
    """Grade a run against hidden truth (WS5 part A)."""
    from precedent.grader.grade import RUNS
    from precedent.grader.grade import grade as grade_run

    result = grade_run(seed, task, run)
    for item in result.items:
        line = f"{item.result:<8} {item.kind:<9} {item.name:<26} expected {item.expected!r}"
        if item.result != "pass":
            line += f", got {item.actual!r}"
        typer.echo(line)
    typer.echo(f"Overall: {result.overall}" + (f" ({result.note})" if result.note else ""))
    (RUNS / run).mkdir(parents=True, exist_ok=True)
    (RUNS / run / "grade.json").write_text(result.model_dump_json(indent=2))
    raise typer.Exit(code={"pass": 0, "fail": 1}.get(result.overall, 2))


@app.command("eval")
def eval_(
    template: str = "northwind",
    seeds: str = "7,8",
    workers: str = "precedent,baseline",
    tasks: str = "T1_figma",
    repeats: int = 1,
) -> None:
    """Seeds x workers x repeats, graded (WS5 part C)."""
    _todo("WS5_verify_eval")


@app.command()
def console(port: int = 8000) -> None:
    """Serve the product screen (WS6)."""
    _todo("WS6_console")


if __name__ == "__main__":
    app()
