"""Verify the README's public media, local links, evidence and privacy boundaries."""

from __future__ import annotations

import hashlib
import json
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    readme = (ROOT / "README.md").read_text()
    targets = re.findall(r"\]\(([^)]+)\)", readme)
    targets += re.findall(r'(?:src|srcset)="([^"]+)"', readme)
    for target in targets:
        parsed = urlsplit(target)
        if not parsed.scheme and parsed.path:
            assert (ROOT / unquote(parsed.path)).exists(), f"Broken local link: {target}"
        else:
            assert parsed.scheme == "https", f"Insecure public link: {target}"
            assert "localhost" not in parsed.netloc, target
    assert "ic-04.github.io" not in readme, "README should not require a separate site"
    assert "flowchart LR" in readme and readme.count("<details>") == readme.count("</details>")
    for path in (ROOT / "assets/readme").glob("*.svg"):
        ET.parse(path)
    manifest = json.loads((ROOT / "assets/readme/manifest.json").read_text())
    total = 0
    for asset in manifest["assets"]:
        path = ROOT / "assets/readme" / asset["file"]
        assert path.is_file() and path.stat().st_size == asset["bytes"], path
        total += path.stat().st_size
    assert total < 10 * 1024**2, "Embedded media exceeds 10 MiB"
    for run in manifest["runs"]:
        public = ROOT / "docs/evidence" / f"{run['id']}.json"
        summary = json.loads(public.read_text())
        for rel, digest in summary["source_digests"].items():
            original = ROOT / "runs" / run["id"] / rel
            if original.exists():
                assert hashlib.sha256(original.read_bytes()).hexdigest() == digest
        original = ROOT / "runs" / run["id"] / "tribunal/verdict.json"
        if original.exists():
            verdict = json.loads(original.read_text())
            assert summary["assessments"]["tribunal"]["overall"] == verdict["overall"]
            assert summary["assessments"]["tribunal"]["counts"] == verdict["counts"]
        assert not re.search(r"[\w.%+-]+@(gmail\.com|iitbbs\.ac\.in)", public.read_text())
        assert "evidence" not in summary.get("draft", {})
    public_text = readme + "".join(p.read_text() for p in (ROOT / "docs/evidence").glob("*.json"))
    assert not re.search(r"AIza[\w-]{30,}|gh[pousr]_[A-Za-z0-9]{20,}", public_text)
    print(
        f"README checks passed: {len(targets)} links, {len(readme.split())} words, "
        f"{total / 1024**2:.2f} MiB media, four verdicts matched to retained sources."
    )


if __name__ == "__main__":
    main()
