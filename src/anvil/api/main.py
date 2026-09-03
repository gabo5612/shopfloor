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

from anvil import cache
from anvil.ingest import JOBS, backfill_embeddings, refresh_stale, start_job
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
    cached: bool = False
    cache_id: int | None = None
    similarity: float | None = None
    cache_hits: int | None = None
    confirmed: bool | None = None
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

    hit = cache.lookup(DSN, q.question, q.lang)
    if hit:
        with _conn() as c:
            rows = c.execute(
                """SELECT c.doc_id, d.title, d.revision, d.superseded_by,
                          c.page_from, c.page_to, c.section_path, c.content
                   FROM chunk c JOIN document d ON d.doc_id = c.doc_id
                   WHERE c.chunk_id = ANY(%s)""", (hit.chunk_ids,),
            ).fetchall()
        return Answer(
            answer=hit.answer, abstained=False, cached=True,
            cache_id=hit.cache_id, similarity=hit.similarity,
            cache_hits=hit.hits, confirmed=hit.confirmed,
            reason=f"Respuesta ya verificada, reutilizada ({hit.similarity:.0%} "
                   f"de coincidencia con: \u201c{hit.question}\u201d).",
            citations=[
                Citation(doc_id=r[0], title=r[1], revision=r[2], superseded_by=r[3],
                         page_from=r[4], page_to=r[5], section_path=r[6],
                         snippet=r[7][:700])
                for r in rows
            ],
            latency_ms=int((time.perf_counter() - t0) * 1000),
            verifier_passed=True,
        )

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

    cache.store(DSN, q.question, q.lang, gen.answer, [h.chunk_id for h in hits])
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
    allowed = (".pdf", ".md", ".markdown")
    if not file.filename or not file.filename.lower().endswith(allowed):
        raise HTTPException(400, "Solo se aceptan archivos .pdf, .md o .markdown")
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


class Feedback(BaseModel):
    cache_id: int
    correct: bool


@app.post("/api/feedback")
def feedback(f: Feedback) -> dict:
    """Confirmacion humana. Un 👎 borra la entrada: no se vuelve a servir."""
    cache.set_confirmed(DSN, f.cache_id, f.correct)
    return {"ok": True}


@app.get("/api/admin/cache")
def cache_list() -> list[dict]:
    with _conn() as c:
        rows = c.execute(
            """SELECT cache_id, question, lang, left(answer, 160), hits,
                      confirmed, stale, created_at, refreshed_at
               FROM qa_cache ORDER BY stale DESC, hits DESC, cache_id DESC
               LIMIT 100"""
        ).fetchall()
    return [
        {"cache_id": r[0], "question": r[1], "lang": r[2], "answer": r[3],
         "hits": r[4], "confirmed": r[5], "stale": r[6],
         "created_at": r[7].isoformat(),
         "refreshed_at": r[8].isoformat() if r[8] else None}
        for r in rows
    ]


@app.post("/api/admin/cache/refresh")
def cache_refresh() -> dict:
    return {"refreshed": refresh_stale(DSN)}


@app.delete("/api/admin/cache/{cache_id}")
def cache_delete(cache_id: int) -> dict:
    with _conn() as c:
        c.execute("DELETE FROM qa_cache WHERE cache_id = %s", (cache_id,))
    return {"deleted": cache_id}
