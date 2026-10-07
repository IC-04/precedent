"""Failure classes and their fixed responses, plus the write gate.

Retrying is not reliability: the safe response to a page that did not load is the
dangerous response to a payment that may have gone through. So each failure is named
first, and each name has one response, written here as code rather than prompt text.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from precedent.contracts import FailureKind

ADVICE = {
    FailureKind.tool: "A page or service failed on a read. Retry the same read; it changes "
    "nothing. After two failed retries, report it.",
    FailureKind.interface: "The page did not accept that action. Take a fresh snapshot, find "
    "the control again by its visible label, and fix what the page says is wrong.",
    FailureKind.uncertain_write: "A save was sent but its result is unknown: it may have "
    "landed. Do not save again. Search for the record by its business key (for example the "
    "invoice number and vendor). If it exists, adopt it and continue. Only if the search "
    "clearly shows it is absent, record a decision and retry once.",
    FailureKind.missing_authority: "No source governs this choice. Ask one specific question "
    "with ask_human, naming the options and the evidence for each.",
    FailureKind.business_contradiction: "The evidence contradicts the request. Stop and "
    "finish with outcome 'blocked', citing the evidence.",
}

MAX_TOOL_RETRIES = 2
MAX_UNCERTAIN_WRITES = 2  # the second one ends the run with 'unknown'


def classify_response(
    method: str, status: int | None, timed_out: bool = False
) -> FailureKind | None:
    """Classify one HTTP exchange seen by the gateway. None means no failure."""
    is_write = method.upper() != "GET"
    if timed_out or status is None or status >= 500:
        return FailureKind.uncertain_write if is_write else FailureKind.tool
    if status in (400, 404, 409, 422):
        return FailureKind.interface
    return None


def classify_tool_error(text: str) -> FailureKind:
    """Classify a browser-tool error (element gone, option missing, timeout...)."""
    lowered = text.lower()
    if "timeout" in lowered or "net::" in lowered:
        return FailureKind.tool
    return FailureKind.interface


@dataclass
class WriteGate:
    """Decides whether a write may leave the browser.

    - A write needs a decision with sources recorded since the last write.
    - After an uncertain write, writes stay locked until the worker has searched (any GET)
      and then recorded a new decision. A second uncertain write is fatal.
    """

    permit: bool = False
    locked: bool = False
    searched: bool = False
    uncertain: int = 0
    writes: list[tuple[str, str, int | None]] = field(default_factory=list)

    @property
    def fatal(self) -> bool:
        return self.uncertain >= MAX_UNCERTAIN_WRITES

    def on_decision(self, sources: list[str]) -> str:
        if not sources:
            return "A decision needs at least one source. Nothing was permitted."
        if self.locked and not self.searched:
            return (
                "A save is uncertain. Search for the record by its business key "
                "before deciding again."
            )
        self.permit, self.locked = True, False
        return "Decision recorded. One save is now permitted."

    def on_request(self, method: str) -> str | None:
        """None to allow; otherwise the reason the request is refused."""
        if method.upper() == "GET":
            if self.locked:
                self.searched = True
            return None
        if self.fatal:
            return "Writes are stopped: two saves had unknown results."
        if self.locked:
            return "A previous save is uncertain. Search for it before saving anything."
        if not self.permit:
            return "Record a decision with sources (record_decision) before saving."
        self.permit = False
        return None

    def on_response(
        self, method: str, path: str, status: int | None, timed_out: bool = False
    ) -> FailureKind | None:
        if method.upper() == "GET":
            return classify_response(method, status, timed_out)
        kind = classify_response(method, status, timed_out)
        self.writes.append((method.upper(), path, status))
        if kind is FailureKind.uncertain_write:
            self.uncertain += 1
            self.locked, self.searched = True, False
        elif kind is FailureKind.interface:
            self.permit = True  # the app refused it, nothing changed: the decision still stands
        return kind
