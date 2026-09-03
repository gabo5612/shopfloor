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
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from anvil.ingest import JOBS, backfill_embeddings, start_job
from anvil.generate import answer_question
from anvil.retrieve import search

UPLOAD_DIR = Path(os.environ.get("ANVIL_DOCS", Path.home() / "anvil-docs"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

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
    answer: str | None = None
    abstained: bool
    needs_clarification: bool = False
    clarify_question: str | None = None
    options: list[str] = []
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
    """Retrieval hibrido. Aun sin generacion: devuelve los pasajes con su cita."""
    t0 = time.perf_counter()
    hits = search(DSN, q.question, lang=q.lang, k=6)
    ms = int((time.perf_counter() - t0) * 1000)

    if not hits:
        return Answer(
            answer=None,
            abstained=True,
            reason="No se encontro nada en la documentacion indexada para esa consulta.",
            latency_ms=ms,
        )

    gen = answer_question(q.question, hits, lang=q.lang)
    ms = int((time.perf_counter() - t0) * 1000)

    cites = [
        Citation(
            doc_id=h.doc_id, title=h.title, revision=h.revision,
            superseded_by=h.superseded_by, page_from=h.page_from,
            page_to=h.page_to, section_path=h.section_path,
            snippet=h.content[:700],
        )
        for h in hits
    ]

    if gen.needs_clarification:
        return Answer(
            abstained=False, needs_clarification=True,
            clarify_question=gen.clarify_question, options=gen.options,
            reason="La documentacion da mas de una respuesta segun un dato que falta.",
            citations=cites, latency_ms=ms, verifier_passed=True,
        )

    if gen.abstained:
        return Answer(
            abstained=True,
            reason=(gen.verdict.reason if gen.verdict
                    else "La respuesta no esta en la documentacion indexada."),
            citations=cites, latency_ms=ms,
            verifier_passed=False if gen.verdict else None,
        )

    return Answer(
        answer=gen.answer, abstained=False,
        reason=gen.verdict.reason if gen.verdict else None,
        citations=cites, latency_ms=ms, verifier_passed=True,
    )


@app.get("/")
def portal() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


# ---------------------------------------------------------------- admin


@app.post("/api/admin/upload")
async def upload(
    file: UploadFile = File(...),
    title: str = Form(""),
    revision: str = Form(""),
    vendor: str = Form(""),
    equipment_tag: str = Form(""),
    lang: str = Form("en"),
) -> dict:
    if not file.filename or not file.filename.lower().endswith(".pdf"):
        raise HTTPException(400, "Solo se aceptan archivos .pdf")
    dest = UPLOAD_DIR / file.filename
    dest.write_bytes(await file.read())
    job = start_job(
        dest, DSN,
        title=title.strip() or dest.stem,
        revision=revision.strip() or None,
        vendor=vendor.strip() or None,
        equipment_tag=equipment_tag.strip() or None,
        lang=lang,
    )
    return job.as_dict()


@app.get("/api/admin/jobs")
def jobs() -> list[dict]:
    return [j.as_dict() for j in sorted(JOBS.values(), key=lambda x: -x.started_at)]


@app.get("/api/admin/documents")
def documents() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT d.doc_id, d.title, d.revision, d.vendor, d.equipment_tag,
                      d.lang, d.n_pages, d.ingested_at,
                      (SELECT count(*) FROM chunk WHERE doc_id=d.doc_id) AS chunks
               FROM document d ORDER BY d.ingested_at DESC"""
        ).fetchall()
    return [
        {"doc_id": r[0], "title": r[1], "revision": r[2], "vendor": r[3],
         "equipment_tag": r[4], "lang": r[5], "n_pages": r[6],
         "ingested_at": r[7].isoformat(), "chunks": r[8]}
        for r in rows
    ]


@app.delete("/api/admin/documents/{doc_id}")
def delete_document(doc_id: str) -> dict:
    with _conn() as c:
        c.execute("DELETE FROM document WHERE doc_id=%s", (doc_id,))
    return {"deleted": doc_id}


@app.get("/admin")
def admin_page() -> FileResponse:
    return FileResponse(WEB_DIR / "admin.html")


@app.post("/api/admin/backfill")
def backfill() -> dict:
    return backfill_embeddings(DSN).as_dict()
