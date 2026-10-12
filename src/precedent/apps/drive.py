"""Drive: folders, files, a viewer with the extracted text, and downloads."""

from __future__ import annotations

import hashlib
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
import uuid
from pathlib import Path
from typing import Annotated
from xml.sax.saxutils import escape

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pypdf import PdfReader

from precedent.apps.common import get_conn, people, render

router = APIRouter(prefix="/drive")
Conn = Annotated[sqlite3.Connection, Depends(get_conn)]


def _path(request: Request, rel: str) -> Path | None:
    """The file on disk, only if it sits inside this world's files folder."""
    base = (request.app.state.world / "files").resolve()
    path = (request.app.state.world / rel).resolve()
    return path if path.is_relative_to(base) and path.is_file() else None


def extract_text(path: Path, mime: str) -> str:
    if mime == "application/pdf":
        pages = PdfReader(path).pages
        return "\n\n".join(f"Page {i + 1}\n{p.extract_text()}" for i, p in enumerate(pages))
    return path.read_text(errors="replace")


@router.get("/")
def home(request: Request, conn: Conn):
    folders = conn.execute(
        "SELECT folder, count(*) AS n, max(uploaded_at) AS latest FROM files"
        " GROUP BY folder ORDER BY folder"
    ).fetchall()
    return render(request, "drive/home.html", folders=folders)


def _missing(request: Request, what: str):
    return render(request, "drive/home.html", code=404, folders=[], missing=what)


@router.get("/f/{fid}")
def viewer(request: Request, conn: Conn, fid: str):
    f = conn.execute("SELECT * FROM files WHERE id = ?", [fid]).fetchone()
    path = _path(request, f["path"]) if f else None
    if f is None or path is None:
        return _missing(request, fid)
    return render(
        request,
        "drive/file.html",
        f=f,
        text=extract_text(path, f["mime"]),
        size=path.stat().st_size,
        pages=min(len(PdfReader(path).pages), 20) if f["mime"] == "application/pdf" else 0,
        names=people(conn),
        attachment=conn.execute(
            "SELECT 1 FROM mail_attachments WHERE file_id = ?", [fid]
        ).fetchone()
        is not None,
    )


@router.get("/f/{fid}/download")
def download(request: Request, conn: Conn, fid: str):
    f = conn.execute("SELECT * FROM files WHERE id = ?", [fid]).fetchone()
    path = _path(request, f["path"]) if f else None
    if f is None or path is None:
        return _missing(request, fid)
    return FileResponse(path, media_type=f["mime"], filename=f["name"])


PREVIEW_LOCK = threading.Lock()


@router.get("/f/{fid}/preview/{page}.png")
def preview(request: Request, conn: Conn, fid: str, page: int):
    """Render the actual bytes. Cache outside the world; never rewrite source documents."""
    f = conn.execute("SELECT * FROM files WHERE id = ?", [fid]).fetchone()
    path = _path(request, f["path"]) if f else None
    if not path or f["mime"] != "application/pdf":
        raise HTTPException(404, "PDF not found")
    if not 1 <= page <= min(len(PdfReader(path).pages), 20):
        raise HTTPException(404, "Page not found")
    binary = os.getenv("PRECEDENT_PDFTOPPM") or shutil.which("pdftoppm")
    if not binary:
        raise HTTPException(503, "Visual preview needs Poppler; extracted text is available")
    key = hashlib.sha256(path.read_bytes()).hexdigest()
    cache = Path(tempfile.gettempdir()) / "precedent-previews" / key
    cache.mkdir(parents=True, exist_ok=True)
    image = cache / f"{page}.png"
    font_config = Path(tempfile.gettempdir()) / "precedent-previews" / "fonts.conf"
    if not font_config.exists():
        font_dirs = [
            Path("/System/Library/Fonts"),
            Path("/Library/Fonts"),
            Path("/usr/share/fonts"),
            Path(__file__).with_name("static") / "fonts",
        ]
        config = "<fontconfig>" + "".join(
            f"<dir>{escape(str(d))}</dir>" for d in font_dirs if d.exists()
        )
        config += f"<cachedir>{font_config.parent / 'font-cache'}</cachedir></fontconfig>"
        font_config.write_text(config)
    env = {**os.environ, "FONTCONFIG_FILE": os.getenv("FONTCONFIG_FILE", str(font_config))}
    with PREVIEW_LOCK:
        if not image.exists() or not image.read_bytes().startswith(b"\x89PNG"):
            pending = cache / f"pending-{uuid.uuid4().hex}.png"
            try:
                subprocess.run(
                    [
                        binary,
                        "-f",
                        str(page),
                        "-l",
                        str(page),
                        "-scale-to",
                        "1300",
                        "-singlefile",
                        "-png",
                        str(path),
                        str(pending.with_suffix("")),
                    ],
                    timeout=12,
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    env=env,
                )
                if not pending.is_file() or not pending.read_bytes().startswith(b"\x89PNG"):
                    raise OSError("Renderer returned no PNG")
                pending.replace(image)
            except (subprocess.SubprocessError, OSError) as exc:
                raise HTTPException(503, "Preview unavailable; use extracted text") from exc
            finally:
                pending.unlink(missing_ok=True)
    return FileResponse(
        image, media_type="image/png", headers={"Cache-Control": "private, max-age=3600"}
    )


@router.get("/{folder:path}")
def folder(request: Request, conn: Conn, folder: str):
    files = conn.execute("SELECT * FROM files WHERE folder = ? ORDER BY name",
                         [folder]).fetchall()  # fmt: skip
    if not files:
        return _missing(request, folder)
    return render(request, "drive/folder.html", folder=folder, files=files, names=people(conn))
