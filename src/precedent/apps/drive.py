"""Drive: folders, files, a viewer with the extracted text, and downloads."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, Request
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
        names=people(conn),
    )


@router.get("/f/{fid}/download")
def download(request: Request, conn: Conn, fid: str):
    f = conn.execute("SELECT * FROM files WHERE id = ?", [fid]).fetchone()
    path = _path(request, f["path"]) if f else None
    if f is None or path is None:
        return _missing(request, fid)
    return FileResponse(path, media_type=f["mime"], filename=f["name"])


@router.get("/{folder:path}")
def folder(request: Request, conn: Conn, folder: str):
    files = conn.execute("SELECT * FROM files WHERE folder = ? ORDER BY name",
                         [folder]).fetchall()  # fmt: skip
    if not files:
        return _missing(request, folder)
    return render(request, "drive/folder.html", folder=folder, files=files, names=people(conn))
