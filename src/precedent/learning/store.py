"""Durable evidence registry. No company DB or privileged evaluation inputs."""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path

CRITICAL = {
    "Vendor",
    "Invoice number",
    "Amount",
    "Invoice date",
    "Due date",
    "Account",
    "Approver",
    "Status",
    "approval_status",
    "Attachment",
    "bill_count",
}
INVOICE_PROCEDURE = """Enter and route the invoice selected by the current task.
Parameters: vendor identity and an invoice selector (a document or latest invoice).
Read current company policy and authoritative instructions. Establish the current vendor,
invoice and approval/accounting rules from their sources; memories are suggestions to check.
Read the vendor record and edit form before any write, without saving, for verification.
If latest is requested, compare accessible invoice candidates by invoice date; clarify ties.
Reconcile vendor plus invoice number before creating or retrying any bill. If it is already
recorded, inspect its values and routing; never create a duplicate or blindly route again.
Record source-backed decisions before each consequential write. Use only existing browser
tools and the gateway. Enter values from the invoice and current policy using fresh UI refs.
Observe the saved bill and approval request. Verify vendor, invoice number, amount/currency,
both dates, account, attachment identity, approver, status and duplicate count afresh.
Do not change vendor data, send email or approve payment. Applicable dated internal authority
governs over older practice; a specific exception governs over a general rule. Ask for human
help when current authorities genuinely conflict or applicability cannot be established.
A changed source requires fresh authority resolution.
The procedure grants no new permission and contains no saved company values or click sequence.
"""


def root_for(runs_root: Path) -> Path:
    return Path(os.getenv("PRECEDENT_MEMORY_ROOT", str(runs_root.resolve().parent / "learning")))


def scope_for(identity: dict) -> str:
    instance = identity.get("memory_id", identity.get("instance_id", ""))
    if len(instance) != 32 or any(c not in "0123456789abcdef" for c in instance):
        raise ValueError("No valid company instance for memory")
    return ("google:" if identity.get("connector") == "google" else "local:") + instance + ":ava"


def stamp() -> str:
    return datetime.now(UTC).isoformat()


class Store:
    def __init__(self, root: Path):
        self.root = root
        root.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS entries (
                id TEXT PRIMARY KEY, scope TEXT NOT NULL, kind TEXT NOT NULL,
                title TEXT NOT NULL, status TEXT NOT NULL, version INTEGER NOT NULL,
                run_id TEXT, created TEXT NOT NULL, updated TEXT NOT NULL,
                payload TEXT NOT NULL)""")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS scoped_entries ON entries(scope, kind, status)"
            )
            conn.execute("""CREATE TABLE IF NOT EXISTS retrievals (
                scope TEXT, run_id TEXT, entry_id TEXT, version INTEGER, at TEXT)""")

    @contextmanager
    def connect(self):
        conn = sqlite3.connect(self.root / "registry.sqlite", timeout=5)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        try:
            with conn:
                yield conn
        finally:
            conn.close()

    @staticmethod
    def decode(row):
        item = dict(row)
        item["payload"] = json.loads(item["payload"])
        return item

    def get(self, scope: str, identifier: str) -> dict:
        with self.connect() as conn:
            row = conn.execute(
                "SELECT * FROM entries WHERE scope=? AND id=?", (scope, identifier)
            ).fetchone()
        if row is None:
            raise KeyError("Learning entry not found in this workspace")
        return self.decode(row)

    def list(self, scope: str, query: str = "", kind: str | None = None) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM entries WHERE scope=? ORDER BY updated DESC", (scope,)
            ).fetchall()
        return [
            self.decode(r)
            for r in rows
            if (not kind or r["kind"] == kind)
            and (not query or query.casefold() in (r["title"] + r["payload"]).casefold())
        ]

    def put(
        self,
        scope: str,
        kind: str,
        title: str,
        payload: dict,
        *,
        identifier: str | None = None,
        status: str = "observed",
        run_id: str | None = None,
    ) -> dict:
        identifier = identifier or uuid.uuid4().hex
        now = stamp()
        with self.connect() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO entries VALUES (?,?,?,?,?,?,?,?,?,?)",
                (identifier, scope, kind, title, status, 1, run_id, now, now, json.dumps(payload)),
            )
        return self.get(scope, identifier)

    def revise(
        self,
        scope: str,
        identifier: str,
        *,
        status: str | None = None,
        correction: str | None = None,
        payload: dict | None = None,
    ) -> dict:
        item = self.get(scope, identifier)
        body = payload if payload is not None else item["payload"]
        history = list(body.get("history", []))
        history.append(
            {
                "version": item["version"],
                "status": item["status"],
                "at": item["updated"],
                "correction": body.get("correction"),
                "validation_run": (item["payload"].get("validation") or {}).get("run_id"),
            }
        )
        body["history"] = history
        if correction is not None:
            body["correction"] = correction[:3000]
            body["correction_note"] = "Human correction; revalidate against current sources."
            status = "needs_review"
        with self.connect() as conn:
            updated = conn.execute(
                "UPDATE entries SET status=?,version=version+1,updated=?,payload=? "
                "WHERE scope=? AND id=? AND version=?",
                (
                    status or item["status"],
                    stamp(),
                    json.dumps(body),
                    scope,
                    identifier,
                    item["version"],
                ),
            )
            if updated.rowcount != 1:
                raise ValueError("Learning changed during review; reload before saving")
        if (
            item["kind"] == "knowledge"
            and not body.get("context_cache")
            and (status == "archived" or correction is not None)
        ):
            for candidate in self.list(scope, kind="knowledge"):
                if (
                    candidate["payload"].get("context_cache")
                    and candidate["status"] == "needs_revalidation"
                ):
                    self.revise(scope, candidate["id"], status="invalidated")
        return self.get(scope, identifier)

    def ingest(self, scope: str, run_id: str, events: list[dict], sources: dict) -> list[dict]:
        ends = [e["data"] for e in events if e["type"] == "run_finished"]
        if len(ends) != 1 or any(e["run_id"] != run_id for e in events):
            raise ValueError("Learning requires one completed, bound run")
        company = next(
            (e["data"].get("company") for e in events if e["data"].get("kind") == "company"), None
        )
        if not company or scope_for(company) != scope:
            raise ValueError("Learning run belongs to another workspace")
        start = next(e["data"] for e in events if e["type"] == "run_started")
        checks = list(
            {e["data"]["condition_id"]: e["data"] for e in events if e["type"] == "check"}.values()
        )
        observed = [
            c
            for c in checks
            if c.get("result") == "pass" and c.get("verifier_version") == 2 and c.get("claims")
        ]
        uncertain = [c for c in checks if c not in observed]
        family = next(
            (
                e["data"].get("task_family", "invoice")
                for e in events
                if e["type"] == "goal_contract"
            ),
            "invoice",
        )
        if family.startswith("google_"):
            # Persist procedural proof metadata, never copied inbox text or model summaries.
            observed = [
                {
                    k: c[k]
                    for k in ("condition_id", "result", "claims", "verifier_version")
                    if k in c
                }
                for c in observed
            ]
            uncertain = [
                {
                    k: c[k]
                    for k in ("condition_id", "result", "claims", "verifier_version")
                    if k in c
                }
                for c in uncertain
            ]
            sources = {}
        payload = {
            "task_family": family,
            "outcome": ends[0]["outcome"],
            "observed": observed,
            "uncertain": uncertain,
            "sources": sources,
            "request": start.get("request", ""),
            "lesson": (
                "Verified claims: "
                + (", ".join(sorted({key for c in observed for key in c["claims"]})) or "none")
                + ". "
                + (f"{len(uncertain)} conditions still need proof. " if uncertain else "")
                + (
                    "Recheck current scheduling sources, availability and existing drafts "
                    "before repeating work."
                    if family == "meeting" or family.startswith("google_")
                    else "Recheck current policy and the invoice business key "
                    "before repeating work."
                )
            ),
            "cost": {k: ends[0].get(k) for k in ("seconds", "tokens_in", "tokens_out", "steps")},
            "verifier_version": 2,
            "revalidate": "Before every consequential write",
        }
        eid = hashlib.sha256((scope + run_id + ":episode").encode()).hexdigest()[:32]
        entries = [
            self.put(
                scope,
                "episode",
                start.get("request", "Task"),
                payload,
                identifier=eid,
                run_id=run_id,
            )
        ]
        for event in events:
            if event["type"] != "precedent" or event["data"].get("status") != "usable":
                continue
            p = event["data"]
            if not p.get("governing"):
                continue
            kid = hashlib.sha256((scope + run_id + p["id"]).encode()).hexdigest()[:32]
            entries.append(
                self.put(
                    scope,
                    "knowledge",
                    p["rule"],
                    {
                        "governing": p["governing"],
                        "supporting": p.get("supporting", []),
                        "sources": sources,
                        "revalidate": "Current authoritative source must be read again",
                        "lesson": p["rule"],
                        "effective": p["governing"].get("dated"),
                    },
                    identifier=kid,
                    status="needs_revalidation",
                    run_id=run_id,
                )
            )
        return entries

    def draft_skill(self, scope: str, episode_id: str) -> dict:
        episode = self.get(scope, episode_id)
        if episode["kind"] != "episode":
            raise ValueError("Choose a task learning note")
        family = episode["payload"].get("task_family", "invoice")
        if family.startswith("google_"):
            if episode["payload"].get("outcome") != "pass" or episode["payload"].get("uncertain"):
                raise ValueError("A Google skill candidate requires independently verified success")
            return self.put(
                scope,
                "skill",
                "Complete verified Google " + family[7:] + " work",
                {
                    "instructions": "Use granted Google capabilities and the trusted task. "
                    "Read fresh selected sources and existing native work. "
                    "Read Reply-To headers. Recheck owned calendar availability for scheduling. "
                    "Record decisions before writes. Save unsent drafts or explicitly requested "
                    "owner-only holds. Reconcile uncertain writes; preserve human edits. Verify "
                    "native IDs, content, permissions and current source versions afresh.",
                    "parameters": ["Current task", "Selected Google sources"],
                    "source_episode": episode_id,
                    "source_run": episode["run_id"],
                    "missing_coverage": ["Independent candidate validation"],
                    "validation": None,
                    "accepted_at": None,
                    "scope_note": "Procedure candidate; no saved mail content or new permissions.",
                },
                status="draft",
                run_id=episode["run_id"],
            )
        if episode["payload"].get("task_family", "invoice") != "invoice":
            raise ValueError(
                "This task keeps a learning note; meeting skill validation is not available"
            )
        covered = set().union(*(set(c.get("claims", [])) for c in episode["payload"]["observed"]))
        missing = sorted(CRITICAL - covered)
        return self.put(
            scope,
            "skill",
            "Enter and route a vendor invoice",
            {
                "instructions": INVOICE_PROCEDURE,
                "parameters": ["Vendor identity", "Invoice selector"],
                "source_episode": episode_id,
                "source_run": episode["run_id"],
                "missing_coverage": missing,
                "validation": None,
                "accepted_at": None,
                "scope_note": "Invoice entry and routing; fresh company policy required.",
            },
            status="draft",
            run_id=episode["run_id"],
        )

    def activate(self, scope: str, identifier: str) -> dict:
        item = self.get(scope, identifier)
        p = item["payload"]
        if (
            item["kind"] != "skill"
            or item["status"] != "validated"
            or p.get("missing_coverage")
            or not (p.get("validation") or {}).get("passed")
        ):
            raise ValueError("Complete proof and a successful sandbox validation are required")
        expected_hash = hashlib.sha256(p["instructions"].encode()).hexdigest()
        if p["validation"].get("procedure_hash") != expected_hash:
            raise ValueError("The procedure changed after validation")
        p["accepted_at"] = stamp()
        return self.revise(scope, identifier, status="active", payload=p)

    def record_retrieval(self, scope: str, run_id: str, entry: dict):
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO retrievals VALUES (?,?,?,?,?)",
                (scope, run_id, entry["id"], entry["version"], stamp()),
            )

    def forget(self, scope: str):
        with self.connect() as conn:
            conn.execute("DELETE FROM entries WHERE scope=?", (scope,))
            conn.execute("DELETE FROM retrievals WHERE scope=?", (scope,))
        cache = self.root / "recall.sqlite"
        if cache.exists():
            with sqlite3.connect(cache) as conn:
                conn.execute("DELETE FROM memory_events WHERE user_id=?", (scope,))


def revalidate_sources(
    store: Store, scope: str, entries: list[dict], captured: dict[str, str]
) -> list[str]:
    """Compare remembered authority with pages already freshly read by the worker."""
    invalidated = []
    for item in entries:
        if item["kind"] != "knowledge":
            continue
        ref = item["payload"].get("governing", {}).get("ref", "")
        app, _, identifier = ref.partition(":")
        prefix = {"mail": "/mail/m/", "drive": "/drive/f/", "chat": "/chat/"}
        path = prefix.get(app, "") + identifier.split("#")[0]
        old = item["payload"].get("sources", {}).get(path, {}).get("hash")
        current = hashlib.sha256(captured[path].encode()).hexdigest() if path in captured else None
        if not old or old != current:
            store.revise(scope, item["id"], status="invalidated")
            invalidated.append(item["id"])
    return invalidated


def context_fingerprints(evidence) -> dict[str, str]:
    """Authority set and contents; history is freshly rechecked, not trusted from cache."""
    return {
        e.ref: hashlib.sha256(
            json.dumps(
                {"text": e.text, "dated": e.dated, "internal": e.internal}, sort_keys=True
            ).encode()
        ).hexdigest()
        for e in evidence
        if not e.rows
    }


def cached_candidates(store: Store, scope: str, fingerprints: dict) -> list[dict] | None:
    for entry in store.list(scope, kind="knowledge"):
        payload = entry["payload"]
        if not payload.get("context_cache") or entry["status"] != "needs_revalidation":
            continue
        if payload.get("source_fingerprints") == fingerprints:
            return payload["candidates"]
        store.revise(scope, entry["id"], status="invalidated")
    return None


def cache_candidates(
    store: Store, scope: str, run_id: str, fingerprints: dict, candidates: list[dict], evidence
):
    return store.put(
        scope,
        "knowledge",
        "Company operating rules",
        {
            "context_cache": True,
            "candidates": candidates,
            "source_fingerprints": fingerprints,
            "lesson": (
                "Prior rule candidates. Every reuse rereads authority "
                "and recomputes history support."
            ),
            "revalidate": "Policy source set and contents must match; history is always rechecked.",
            "sources": {
                e.url: {"hash": fingerprints[e.ref], "text": e.text}
                for e in evidence
                if e.ref in fingerprints
            },
        },
        status="needs_revalidation",
        run_id=run_id,
    )
