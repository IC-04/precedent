"""Precedent command line. Each command is filled in by its workstream (see docs/briefs)."""

from __future__ import annotations

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
    _todo("WS1_world")


@app.command()
def apps(seed: int = 7, port: int = 8100) -> None:
    """Serve Mail, Books, Drive and Chat for a seed (WS2)."""
    _todo("WS2_apps")


@app.command()
def run(
    task: str = typer.Option(..., help="Natural-language request"),
    seed: int = 7,
    worker: str = typer.Option("precedent", help="precedent | baseline"),
    resume: str | None = typer.Option(None, help="Resume an unfinished task id"),
    headed: bool = False,
) -> None:
    """Run the worker on a request (WS3)."""
    _todo("WS3_worker_loop")


@app.command()
def grade(seed: int = 7, task: str = "T1_figma", run: str = typer.Option(...)) -> None:
    """Grade a run against hidden truth (WS5 part A)."""
    _todo("WS5_verify_eval")


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
