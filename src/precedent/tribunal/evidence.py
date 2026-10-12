"""Exhibits: the Tribunal's own fresh reads of the company apps.

Read-only GETs straight to the company apps with the Tribunal's own identity, never
through Ava's gateway or her captured pages. Each exhibit keeps the URL, capture time
and a content hash, and record pages also get a screenshot from the Tribunal's own
headless browser.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from precedent.worker.context import read_page
from precedent.worker.verify import CheckPlan, Reader, UnreadablePage, _clean, record_fields

HEADERS = {"X-Precedent-Agent": "tribunal"}
SOURCE = re.compile(r"^/(drive/f/[^/]+|mail/m/[^/]+|books/vendors/[^/]+)$")
TEXT_LIMIT = 3500
OPEN_DETAILS = "document.querySelectorAll('details').forEach((d) => d.open = true)"
RECORD_ID = re.compile(r"[A-Za-z0-9_-]{1,64}")


@dataclass
class Exhibit:
    id: str  # "E1"
    path: str
    title: str
    kind: str  # "record" (what the work produced) or "source" (what governs it)
    text: str
    fields: dict[str, str]
    sha256: str
    captured_at: str
    screenshot: str | None = None  # file name inside the tribunal folder
    boxes: dict[str, list[float]] = field(default_factory=dict)  # label -> x, y, w, h (page px)
    size: list[float] = field(default_factory=list)  # screenshot page width, height
    html: str = field(default="", repr=False)

    def public(self) -> dict:
        return {k: v for k, v in self.__dict__.items() if k != "html"}


def _title(html: str) -> str:
    """The page's own heading, else the first part of its document title."""
    heading = re.search(r"<h1[^>]*>(.*?)</h1>", html, re.S)
    if heading and _clean(heading[1]):
        return _clean(heading[1])[:80]
    return read_page(html).title.split(" · ")[0].strip()


def page_text(html: str) -> str:
    page = read_page(html)
    main = re.search(r"<main[^>]*>(.*?)</main>", html, re.S)
    text = "\n".join(page.pre) or _clean(main[1] if main else html)
    return text[:TEXT_LIMIT]


def targets(plan: CheckPlan, reader: Reader) -> tuple[list[str], list[str]]:
    """Record pages the checks are about, and the source pages they cite."""
    records, sources = [], []
    for spec in plan.checks:
        if spec.primitive in ("bill_field", "approval_status", "count_bills"):
            try:
                ids = (
                    [spec.bill_id]
                    if spec.bill_id
                    else reader.bills_for(spec.invoice_no or "", spec.vendor_id)
                )
            except (httpx.HTTPError, UnreadablePage):
                ids = []
            records += [f"/books/bills/{i}" for i in ids if i and RECORD_ID.fullmatch(i)]
        if (
            spec.vendor_id
            and RECORD_ID.fullmatch(spec.vendor_id)
            and spec.primitive
            in (
                "vendor_field",
                "field_unchanged",
                "vendor_unchanged",
            )
        ):
            records.append(f"/books/vendors/{spec.vendor_id}")
        if spec.source_path and SOURCE.match(spec.source_path):
            sources.append(spec.source_path)
    records = list(dict.fromkeys(records))
    return records, [p for p in dict.fromkeys(sources) if p not in records]


def collect(
    apps_url: str,
    plan: CheckPlan,
    out_dir: Path,
    screenshots: bool = True,
    on_exhibit: Callable[[Exhibit], None] | None = None,
) -> list[Exhibit]:
    """Invoice tasks: the records and sources named by the verification plan."""
    with httpx.Client(base_url=apps_url, headers=HEADERS, timeout=20) as client:
        records, sources = targets(plan, Reader(client, {}, {}))
    return collect_paths(apps_url, records, sources, out_dir, screenshots, on_exhibit)


def collect_paths(
    apps_url: str,
    records: list[str],
    sources: list[str],
    out_dir: Path,
    screenshots: bool = True,
    on_exhibit: Callable[[Exhibit], None] | None = None,
    start: int = 0,
) -> list[Exhibit]:
    """Fresh read-only reads of these pages; records also get screenshots and field boxes."""
    exhibits: list[Exhibit] = []
    with httpx.Client(base_url=apps_url, headers=HEADERS, timeout=20) as client:
        for kind, paths in (("record", records), ("source", sources)):
            for path in dict.fromkeys(paths):
                try:
                    response = client.get(path)
                    response.raise_for_status()
                except httpx.HTTPError:
                    continue
                html = response.text
                exhibits.append(
                    Exhibit(
                        id=f"E{start + len(exhibits) + 1}",
                        path=path,
                        title=_title(html) or path,
                        kind=kind,
                        text=page_text(html),
                        fields=record_fields(html),
                        sha256=hashlib.sha256(html.encode()).hexdigest(),
                        captured_at=datetime.now(UTC).isoformat(timespec="seconds"),
                        html=html,
                    )
                )
    if screenshots:
        _screenshots(apps_url, [e for e in exhibits if e.kind == "record"][:4], out_dir)
    for exhibit in exhibits:
        if on_exhibit:
            on_exhibit(exhibit)
    return exhibits


FIELD_BOXES = """() => {
  const out = {};
  const box = (rects) => {
    const x = Math.min(...rects.map((r) => r.left)) + scrollX;
    const y = Math.min(...rects.map((r) => r.top)) + scrollY;
    const w = Math.max(...rects.map((r) => r.right)) + scrollX - x;
    const h = Math.max(...rects.map((r) => r.bottom)) + scrollY - y;
    return [x, y, w, h].map((v) => Math.round(v));
  };
  document.querySelectorAll("dt").forEach((dt) => {
    const dd = dt.nextElementSibling;
    if (dd && dd.tagName === "DD") {
      out[dt.textContent.trim()] = box([dt.getBoundingClientRect(), dd.getBoundingClientRect()]);
    }
  });
  document.querySelectorAll("table").forEach((t) => {
    const head = [...t.querySelectorAll("th")].map((th) => th.textContent.trim());
    if (head[0] === "Approver" && head[1] === "Status") {
      out.approval_status = box([t.getBoundingClientRect()]);
    }
  });
  const root = document.documentElement;
  return { boxes: out, size: [root.scrollWidth, root.scrollHeight] };
}"""


def _screenshots(apps_url: str, exhibits: list[Exhibit], out_dir: Path) -> None:
    """Best effort: an exhibit without a screenshot still has its text and hash."""
    if not exhibits:
        return
    try:
        from playwright.sync_api import sync_playwright

        out_dir.mkdir(parents=True, exist_ok=True)
        with sync_playwright() as p:
            browser = p.chromium.launch()
            try:
                page = browser.new_page(
                    viewport={"width": 1200, "height": 860}, extra_http_headers=HEADERS
                )
                for exhibit in exhibits:
                    page.goto(apps_url.rstrip("/") + exhibit.path, wait_until="load")
                    # Saved details often sit in collapsed sections; show them before capture.
                    page.evaluate(OPEN_DETAILS)
                    name = f"{exhibit.id}.png"
                    page.screenshot(path=str(out_dir / name), full_page=True)
                    exhibit.screenshot = name
                    try:  # where each labelled field sits, so the screen can point at it
                        layout = page.evaluate(FIELD_BOXES)
                        exhibit.boxes, exhibit.size = layout["boxes"], layout["size"]
                    except Exception:  # noqa: BLE001 - highlights are optional
                        pass
            finally:
                browser.close()
    except Exception:  # noqa: BLE001 - screenshots are corroboration, not the proof
        return
