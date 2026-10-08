"""Public display metadata and actual PDF preview regressions; no privileged answers."""

import hashlib
import json
import shutil

from fastapi.testclient import TestClient
from pypdf import PdfReader

from precedent.apps.server import create_app
from precedent.world.generator import generate


def test_company_metadata_and_visual_pdf_use_actual_world_bytes(tmp_path, monkeypatch):
    monkeypatch.setenv("PRECEDENT_SCENARIO_TOKEN", "test")
    manifest = generate("northwind", 8, tmp_path / "8")
    with TestClient(create_app(8, tmp_path)) as client:
        identity = client.get("/workspace.json").json()
        assert identity["seed"] == 8 and identity["name"] == manifest.company["name"]
        assert (
            identity["world_id"]
            == hashlib.sha256((tmp_path / "8/manifest.json").read_bytes()).hexdigest()
        )
        assert client.get("/").status_code == 200
        # Retrieve a real document through its public app link, not through an answer oracle.
        import io

        document = next(
            d
            for d in identity["documents"]
            if d["name"].endswith(".pdf")
            if "Total due"
            in "".join(
                p.extract_text() or ""
                for p in PdfReader(
                    io.BytesIO(client.get(f"/drive/f/{d['id']}/download").content)
                ).pages
            )
        )
        link = f"/drive/f/{document['id']}"
        view = client.get(link)
        assert "Document preview" in view.text and "Text of the file" in view.text
        preview = client.get(link + "/preview/1.png")
        if shutil.which("pdftoppm"):
            assert preview.status_code == 200 and preview.content.startswith(b"\x89PNG")
        else:
            assert preview.status_code == 503
        assert client.get(link + "/preview/0.png").status_code == 404
        assert client.get(link + "/preview/999.png").status_code == 404
        download = client.get(link + "/download")
        text = PdfReader(io.BytesIO(download.content)).pages[0].extract_text()
        assert "Total due" in text
        assert hashlib.sha256(download.content).hexdigest() in manifest.files.values()
        assert "hidden" not in json.dumps(identity).lower()
