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
