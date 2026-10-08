"""Company context (WS4): gather through the apps' web pages, validate in code."""

import json

from precedent.contracts import Authority, PrecedentStatus
from precedent.worker.context import (
    Candidate,
    Claim,
    as_prompt,
    baseline_prompt,
    gather,
    support,
    validate,
)


def _evidence(live_apps, tmp_path):
    base, _ = live_apps
    return gather(base, tmp_path / "evidence", headers={"X-Precedent-Agent": "ava"})


def test_gather_reads_policies_instructions_and_history(live_apps, tmp_path):
    ev = _evidence(live_apps, tmp_path)
    refs = {e.ref: e for e in ev}
    titles = {e.title for e in ev}
    assert {"AP-Policy-2025.pdf", "AP-SOP-v3.pdf"} <= titles
    cfo = next(e for e in ev if e.app == "mail" and "approvals" in e.title.lower())
    assert cfo.dated == "2026-07-02" and "routes to me" in cfo.text
    history = refs["books:history"]
    assert len(history.rows) == 312
    saved = {p.name for p in (tmp_path / "evidence").iterdir()}
    assert "books_history.json" in saved
    assert json.loads((tmp_path / "evidence" / "books_history.json").read_text())["rows"]


def test_support_is_counted_from_rows(live_apps, tmp_path):
    rows = next(e.rows for e in _evidence(live_apps, tmp_path) if e.rows)
    claim = Claim(field="approver", value="Ana Pereira", account="6400", min_amount=50000,
                  from_date="2026-07-14")  # fmt: skip
    agree, total, others = support(rows, claim)
    assert (agree, total) == (8, 9) and len(others) == 1


def _candidates(cfo_ref):
    return [
        Candidate(rule="Design spend above INR 50,000 is approved by Ana Pereira",
                  governing_ref=cfo_ref, governing_authority=Authority.instruction,
                  claim=Claim(field="approver", value="Ana Pereira", account="6400",
                              min_amount=50000, from_date="2026-07-14"),
                  flags=["SOP 3.2 stale"], status=PrecedentStatus.usable),
        Candidate(rule="Invented rule", governing_ref="mail:m-9999",
                  status=PrecedentStatus.usable),
        Candidate(rule="Linear licences: 6120 or 6340",
                  claim=Claim(field="account", value="6120", vendor="Linear"),
                  status=PrecedentStatus.usable),
    ]  # fmt: skip


def test_validation_drops_uncited_rules_and_recomputes_counts(live_apps, tmp_path):
    ev = _evidence(live_apps, tmp_path)
    cfo = next(e for e in ev if e.app == "mail" and "approvals" in e.title.lower())
    precedents = validate(_candidates(cfo.ref), ev)
    rules = [p.rule for p in precedents]
    assert "Invented rule" not in rules  # its citation was never gathered
    design = precedents[0]
    assert design.support == "8 of 9 bills since 2026-07-14" and design.exceptions
    assert design.governing.dated == "2026-07-02"
    linear = next(p for p in precedents if p.rule.startswith("Linear"))
    assert linear.status == PrecedentStatus.unresolved  # split 5 to 4, nothing governs it
    text = as_prompt(precedents)
    assert "[usable] Design spend" in text and "[unresolved] Linear" in text


def test_baseline_context_is_documents_only(live_apps, tmp_path):
    text = baseline_prompt(_evidence(live_apps, tmp_path))
    assert "AP-SOP-v3.pdf" in text and "routes to me" not in text and "INV-" not in text


def test_bracketed_refs_stale_rules_and_unscoped_claims(live_apps, tmp_path):
    """Regression for run 20261008-134000-04cd: every candidate was dropped for '[mail:m-1]'
    refs, and the stale procedure's rule competed with the later instruction."""
    from precedent.worker.context import validate_with_report

    ev = _evidence(live_apps, tmp_path)
    cfo = next(e for e in ev if e.app == "mail" and "approvals" in e.title.lower())
    sop = next(e for e in ev if e.title == "AP-SOP-v3.pdf")
    candidates = [
        Candidate(rule="Design spend above INR 50,000 routes to Ana Pereira",
                  governing_ref=f"[{cfo.ref}]", supporting_refs=["[books:history]"],
                  claim=Claim(field="approver", value="Ana Pereira", account="6400",
                              min_amount=50000, from_date="2026-07-14"),
                  status=PrecedentStatus.usable),
        Candidate(rule="Route design spend above INR 50,000 to Raj Mehta",
                  governing_ref=f"[{sop.ref}]",
                  claim=Claim(field="approver", value="Raj Mehta", account="6400",
                              min_amount=50000),
                  status=PrecedentStatus.usable),
        Candidate(rule="Payments covering more than one period go to 1400",
                  governing_ref=f" {sop.ref} ", claim=Claim(field="account", value="1400"),
                  status=PrecedentStatus.usable),
    ]  # fmt: skip
    precedents, report = validate_with_report(candidates, ev)
    assert report == {"candidates": 3, "kept": 3, "dropped": []}
    ana, raj, prepaid = precedents
    assert ana.status == PrecedentStatus.usable and ana.support == "8 of 9 bills since 2026-07-14"
    assert raj.status == PrecedentStatus.conflict
    assert raj.flags == [f"superseded by {cfo.ref} from 2026-07-14"]
    assert prepaid.support is None and "support not counted" in prepaid.flags[0]
    text = as_prompt(precedents)
    assert "[usable] Design spend" in text and "[conflict] Route design spend" in text
