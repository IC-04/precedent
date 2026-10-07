"""What the model sees of a page: Playwright MCP's accessibility snapshot, made small.

Playwright MCP writes each page snapshot to a file and returns a link. We read the file,
compact it, and put it in the tool result, so the model sees the page after every
action without spending a step on browser_snapshot. Older snapshots are later reduced
to one line each (see summarize_old), so a long run does not drown in old pages.
"""

from __future__ import annotations

import re
from pathlib import Path

MAX_OPTIONS = 60  # dropdowns list their options on one line up to this many
MAX_ROWS = 25  # rows kept per table
SNAPSHOT_LINK = re.compile(r"\[Snapshot\]\(([^)]+\.yml)\)")
URL = re.compile(r"Page URL: (\S+)")
TITLE = re.compile(r"Page Title: (.*)")
OLD = "[older page snapshot omitted to save space: {url} ({title})]"
ACTIONABLE = (
    "link",
    "button",
    "textbox",
    "combobox",
    "checkbox",
    "radio",
    "searchbox",
    "spinbutton",
    "listbox",
    "option",
    "tab",
    "menuitem",
)
REF = re.compile(r" \[ref=[^\]]+\]")


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _children(lines: list[str], i: int) -> int:
    """Index just past the block of lines nested under lines[i]."""
    base, j = _indent(lines[i]), i + 1
    while j < len(lines) and _indent(lines[j]) > base:
        j += 1
    return j


def _options_line(lines: list[str], indent: int) -> str:
    names = [m.group(1) for line in lines if (m := re.search(r'option "([^"]*)"', line))]
    chosen = [
        m.group(1)
        for line in lines
        if "[selected]" in line and (m := re.search(r'option "([^"]*)"', line))
    ]
    pad = " " * indent
    if len(names) > MAX_OPTIONS:
        picked = ", ".join(chosen)
        return f'{pad}- ({len(names)} options; selected: "{picked}"; choose by visible text)'
    return f'{pad}- options ({len(names)}, selected: "{", ".join(chosen)}"): ' + "; ".join(names)


def _row_line(lines: list[str], indent: int) -> str:
    """One table row as one line: cell texts joined by '|', links keep ref and url."""
    cells, i = [], 1
    while i < len(lines):
        stripped = lines[i].strip()
        if stripped.startswith("- cell"):
            m = re.match(r'- cell "(.*)" \[ref=[^\]]+\]$', stripped)
            cells.append(m.group(1) if m else "")
        elif stripped.startswith("- link") and cells is not None:
            name = re.search(r'"(.*)"', stripped)
            ref = re.search(r"\[ref=([^\]]+)\]", stripped)
            url = lines[i + 1].strip().removeprefix("- /url: ") if i + 1 < len(lines) else ""
            label = (
                f'link "{name.group(1) if name else ""}" [ref={ref.group(1) if ref else ""}] {url}'
            )
            cells[-1] = (cells[-1] + " " + label).strip() if cells else label
        i += 1
    return " " * indent + "- row: " + " | ".join(cells)


def _tidy(line: str) -> str | None:
    """Drop refs on things the model cannot act on, and empty wrapper lines."""
    line = line.replace(" [cursor=pointer]", "")
    role = line.strip().removeprefix("- ").split(" ", 1)[0].rstrip(":")
    if role in ACTIONABLE:
        return line
    line = REF.sub("", line)
    if line.strip() in ("- generic:", "- generic"):
        return None
    return line


def compact_snapshot(yaml_text: str) -> str:
    lines = [line.replace(" [cursor=pointer]", "") for line in yaml_text.splitlines()]
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith(("- combobox", "- listbox")) and stripped.endswith(":"):
            end = _children(lines, i)
            out.append(line)
            out.append(_options_line(lines[i + 1 : end], _indent(line) + 2))
            i = end
            continue
        if stripped.startswith("- rowgroup") and stripped.endswith(":"):
            end = _children(lines, i)
            out.append(line)
            out.extend(_cap_rows(lines[i + 1 : end], _indent(line) + 2))
            i = end
            continue
        tidy = _tidy(line)
        if tidy is not None:
            out.append(tidy)
        i += 1
    return "\n".join(out)


def _cap_rows(lines: list[str], indent: int) -> list[str]:
    out, rows, i = [], 0, 0
    while i < len(lines):
        end = _children(lines, i)
        if _indent(lines[i]) == indent and lines[i].strip().startswith("- row"):
            rows += 1
            if rows <= MAX_ROWS:
                out.append(_row_line(lines[i:end], indent))
            i = end
            continue
        out.extend(x for x in (_tidy(line) for line in lines[i:end]) if x is not None)
        i = end
    if rows > MAX_ROWS:
        out.append(
            " " * indent + f"- ({rows - MAX_ROWS} more rows not shown; narrow the search "
            "or use the next page)"
        )
    return out


def strip_code(text: str) -> str:
    """Drop MCP's 'Ran Playwright code' block: it is for humans, not for the model."""
    return re.sub(r"### Ran Playwright code\n```[a-z]*\n.*?```\n?", "", text, flags=re.S)


def inline_snapshot(text: str, base_dir: Path) -> str:
    """Replace MCP's link to a snapshot file with the compacted snapshot itself."""
    text = strip_code(text)
    m = SNAPSHOT_LINK.search(text)
    if not m:
        return text
    path = Path(m.group(1))
    path = path if path.is_absolute() else base_dir / path
    if not path.exists():
        return text
    body = compact_snapshot(path.read_text())
    return text[: m.start()] + "\n```yaml\n" + body + "\n```" + text[m.end() :]


def page_of(text: str) -> tuple[str, str]:
    url, title = URL.search(text), TITLE.search(text)
    return (url.group(1) if url else ""), (title.group(1).strip() if title else "")


def one_line(text: str) -> str:
    url, title = page_of(text)
    return OLD.format(url=url or "unknown page", title=title)
