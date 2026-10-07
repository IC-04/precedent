"""Guard tests for the non-negotiables in CLAUDE.md. Keep them passing."""

from pathlib import Path

WORKER = Path(__file__).resolve().parents[1] / "src" / "precedent" / "worker"


def _worker_sources():
    return [(p, p.read_text()) for p in WORKER.rglob("*.py")]


def test_worker_never_touches_the_database_or_hidden_truth():
    banned = ["sqlite3", "world.db", "hidden.json", "precedent.world.db", "HiddenTruth"]
    for path, text in _worker_sources():
        for word in banned:
            assert word not in text, (
                f"{path.name} mentions {word!r}; the worker must use the browser"
            )


def test_worker_has_no_company_specific_names():
    banned = ["Northwind", "Globex", "Ana Pereira", "Raj Mehta", "Figma", "Zenith", "FIG-1842"]
    for path, text in _worker_sources():
        for word in banned:
            assert word not in text, f"{path.name} hard-codes {word!r}"


def test_only_runner_and_goal_import_model_sdks():
    """ADK and the model SDKs stay in runner.py and goal.py (architecture D2 and D5)."""
    sdks = ["anthropic", "google.adk", "google.genai", "from google import genai", "openai"]
    allowed = {"runner.py", "goal.py"}
    for path, text in _worker_sources():
        if path.name in allowed:
            continue
        imports = [line for line in text.splitlines() if line.startswith(("import ", "from "))]
        for s in sdks:
            assert not any(s in line for line in imports), (
                f"{path.name} imports {s}; only {sorted(allowed)} may"
            )
