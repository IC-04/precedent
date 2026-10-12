"""The in-run Tribunal: what Ava is told when charges are sent back."""

from precedent.contracts import GoalContract
from precedent.worker.runner import remand_text


def test_remand_states_court_facts_and_labels_juror_opinions():
    goal = GoalContract.model_validate({"request": "r", "outcome": "o", "conditions": [
        {"id": "c1", "text": "The approver is the CFO", "kind": "must_be_true"}]})  # fmt: skip
    record = [
        {"event": "exact", "condition_id": "c1", "evidence": "/books/bills/B-1: found 'Raj'"},
        {"event": "vote", "id": "c1", "ballot": {"observed": "Approver: Raj"}},
    ]
    text = remand_text(goal, {"c1": {"result": "fail", "reason": "An exact check failed"}}, record)
    assert "c1: The approver is the CFO" in text and "found 'Raj'" in text
    assert "A juror noted (unverified): Approver: Raj" in text
    assert "never create a second record" in text and "call finish" in text


def test_only_actionable_charges_are_sent_back():
    from precedent.worker.runner import remand_charges

    verdict = {
        "rulings": {
            "c1": {"result": "fail", "valid_votes": 0},
            "c2": {"result": "disputed", "valid_votes": 6},
            "c3": {"result": "unknown", "valid_votes": 6},  # claimed, and a jury voted
            "c4": {"result": "unknown", "valid_votes": 0},  # claimed, but no jury sat
            "c5": {"result": "unknown", "valid_votes": 6},  # never claimed
            "c6": {"result": "pass", "valid_votes": 6},
        },
        "unsupported_claims": [{"id": "c3"}, {"id": "c4"}],
    }
    assert sorted(remand_charges(verdict)) == ["c1", "c2", "c3"]


def test_the_run_never_passes_when_the_court_disagrees():
    from precedent.worker.runner import combined_outcome

    sat = {"rulings": {"c1": {}}}
    assert combined_outcome("pass", {**sat, "overall": "pass"}) == "pass"
    assert combined_outcome("pass", {**sat, "overall": "fail"}) == "fail"
    assert combined_outcome("pass", {**sat, "overall": "disputed"}) == "unknown"
    assert combined_outcome("pass", {"overall": "unknown", "rulings": {}}) == "pass"  # no court
    assert combined_outcome("fail", {**sat, "overall": "pass"}) == "fail"
    assert combined_outcome("unknown", {**sat, "overall": "pass"}) == "pass"
    assert combined_outcome("blocked", {**sat, "overall": "pass"}) == "blocked"
    assert combined_outcome("unknown", {**sat, "overall": "unknown"}) == "unknown"
