from precedent.contracts import (
    Authority,
    Condition,
    Event,
    GoalContract,
    Precedent,
    PrecedentStatus,
    SourceRef,
)


def test_event_roundtrip():
    gc = GoalContract(
        request="Enter the latest invoice and route it for approval.",
        outcome="One bill exists and awaits approval.",
        conditions=[
            Condition(id="c1", text="Exactly one bill exists", kind="must_be_true"),
            Condition(id="n1", text="Bank details unchanged", kind="must_not_happen"),
        ],
    )
    e = Event(run_id="r1", seq=1, type="goal_contract", data=gc.model_dump())
    again = Event.model_validate_json(e.model_dump_json())
    assert GoalContract.model_validate(again.data) == gc


def test_precedent_requires_status():
    p = Precedent(
        id="p1",
        task_family="enter_invoice",
        rule="Rule",
        governing=SourceRef(app="mail", ref="mail:m-1", authority=Authority.instruction),
        status=PrecedentStatus.usable,
    )
    assert p.status == "usable"
