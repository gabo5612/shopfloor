"""API de anvil + portal web para la planta.

Se sirve en 0.0.0.0 para que cualquier telefono o PC de la LAN lo abra.
Sin CDN, sin fuentes remotas: la planta puede no tener internet (§1).
"""

from __future__ import annotations

import os
import socket
import time
from pathlib import Path

import psycopg
from fastapi import FastAPI
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
DSN = os.environ.get("ANVIL_DSN", "postgresql://anvil:anvil@localhost:5433/anvil")

app = FastAPI(title="anvil", docs_url="/api/docs")


class Ask(BaseModel):
    question: str
    lang: str = "es"


class Citation(BaseModel):
    doc_id: str
    title: str
    revision: str | None = None
    superseded_by: str | None = None
    page_from: int
    page_to: int
    section_path: str | None = None
    snippet: str


class Answer(BaseModel):
    answer: str | None
    abstained: bool
    reason: str | None = None
    citations: list[Citation] = []
    latency_ms: int = 0
    verifier_passed: bool | None = None


def _conn() -> psycopg.Connection:
    return psycopg.connect(DSN, autocommit=True)


@app.get("/api/health")
def health() -> JSONResponse:
    out: dict = {"ok": True, "host": socket.gethostname()}
    try:
        with _conn() as c:
            out["docs"] = c.execute("SELECT count(*) FROM document").fetchone()[0]
            out["chunks"] = c.execute("SELECT count(*) FROM chunk").fetchone()[0]
            out["pgvector"] = c.execute(
                "SELECT extversion FROM pg_extension WHERE extname='vector'"
            ).fetchone()[0]
    except Exception as e:  # la planta debe VER el fallo, no una pagina en blanco
        out["ok"] = False
        out["error"] = str(e)
    return JSONResponse(out, status_code=200 if out["ok"] else 503)


@app.post("/api/ask", response_model=Answer)
def ask(q: Ask) -> Answer:
    """Contrato estable. El retrieval hibrido y el verificador entran en M2-M4.

    Hoy responde con abstencion honesta si el corpus esta vacio: es la
    respuesta CORRECTA, no un placeholder (§3, Problema 4).
    """
    t0 = time.perf_counter()
    with _conn() as c:
        n = c.execute("SELECT count(*) FROM chunk").fetchone()[0]
    ms = int((time.perf_counter() - t0) * 1000)

    if n == 0:
        return Answer(
            answer=None,
            abstained=True,
            reason="No hay documentacion cargada todavia. Ningun documento indexado.",
            latency_ms=ms,
        )
    return Answer(
        answer=None,
        abstained=True,
        reason="Retrieval no implementado aun (M2). Abstenerse es la respuesta correcta.",
        latency_ms=ms,
    )


@app.get("/")
def portal() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")
