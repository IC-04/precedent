"""Verdict rules. Code, not a model: an exact check always beats an opinion."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from precedent.tribunal.jury import Vote

Result = Literal["pass", "fail", "disputed", "unknown"]
Basis = Literal["exact", "jury", "arbiter", "process", "none"]

STRONG = 0.8  # share of valid votes needed for the jury to decide on its own
MIN_VOTES = 4  # fewer valid votes than this cannot decide anything


class Tally(BaseModel):
    holds: int = 0
    does_not_hold: int = 0
    cannot_tell: int = 0
    absent: int = 0

    @property
    def valid(self) -> int:
        return self.holds + self.does_not_hold + self.cannot_tell

    def share(self, answer: str) -> float:
        return getattr(self, answer) / self.valid if self.valid else 0.0


def tally(votes: list[Vote]) -> Tally:
    t = Tally()
    for vote in votes:
        if vote.ballot is None:
            t.absent += 1
        else:
            setattr(t, vote.ballot.answer, getattr(t, vote.ballot.answer) + 1)
    return t


class ChargeVerdict(BaseModel):
    result: Result
    basis: Basis
    reason: str


def rule(exact: str, t: Tally | None, process: bool = False) -> ChargeVerdict:
    """The research table (docs/verifier_patterns_research.md, section 2.6)."""
    decided = t is not None and t.valid >= MIN_VOTES
    holds = decided and t.share("holds") >= STRONG
    refuted = decided and t.share("does_not_hold") >= STRONG
    disagrees = decided and t.share("does_not_hold") >= 0.5
    if exact == "fail":
        return ChargeVerdict(result="fail", basis="exact", reason="An exact check failed")
    if exact == "pass":
        if disagrees:
            return ChargeVerdict(
                result="disputed", basis="exact", reason="Exact check passed but the jury disagrees"
            )
        return ChargeVerdict(result="pass", basis="exact", reason="Exact check passed")
    if process and not disagrees:
        return ChargeVerdict(
            result="pass",
            basis="process",
            reason="No exact check; the run's write log shows no master-data writes",
        )
    if holds:
        return ChargeVerdict(
            result="pass", basis="jury", reason="No exact check; the jury agrees it holds"
        )
    if refuted:
        return ChargeVerdict(
            result="fail", basis="jury", reason="No exact check; the jury agrees it does not hold"
        )
    if decided and (t.holds and t.does_not_hold):
        return ChargeVerdict(
            result="disputed", basis="none", reason="No exact check and the jury is split"
        )
    return ChargeVerdict(
        result="unknown", basis="none", reason="No exact check and too little agreement to decide"
    )


def arbitrate(verdict: ChargeVerdict, exact: str, answer: str | None) -> ChargeVerdict:
    """A disputed charge after the arbiter's single answer."""
    if verdict.result != "disputed" or answer is None:
        return verdict
    if exact == "pass":
        if answer == "holds":
            return ChargeVerdict(
                result="pass",
                basis="exact",
                reason="Exact check passed; the arbiter overruled the jury",
            )
        if answer == "cannot_tell":
            # A split jury and a senior model that finds nothing contrary do not outweigh a
            # proven fact; only an active contradiction reaches a person.
            return ChargeVerdict(
                result="pass",
                basis="exact",
                reason="Exact check passed; the jury split and the senior model found "
                "nothing contrary",
            )
        return verdict.model_copy(
            update={
                "reason": "Exact check passed but the senior model contradicts it; "
                "a person should look"
            }
        )
    if answer in ("holds", "does_not_hold"):
        return ChargeVerdict(
            result="pass" if answer == "holds" else "fail",
            basis="arbiter",
            reason="The jury was split; the arbiter decided",
        )
    return ChargeVerdict(
        result="unknown", basis="none", reason="The jury was split and the arbiter could not tell"
    )


def overall(results: list[str], audit_failed: bool) -> Result:
    if audit_failed or "fail" in results:
        return "fail"
    if "disputed" in results:
        return "disputed"
    if not results or "unknown" in results:
        return "unknown"
    return "pass"
