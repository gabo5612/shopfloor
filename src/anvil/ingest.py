"""Pipeline de ingesta: PDF -> bloques -> chunks -> Postgres.

Se ejecuta en background para no bloquear la subida. El estado vive en memoria
del proceso y lo consulta el panel via /api/admin/jobs.
"""

from __future__ import annotations

import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import psycopg

from anvil.chunk.structural import STRATEGY_VERSION, chunk_blocks
from anvil.embed.client import DIM, MODEL, embed_batched, to_pgvector
from anvil.parse.markdown import parse_markdown
from anvil.parse.pdf import parse_pdf, sha256_of

MAX_CHARS = 1800


@dataclass
class Job:
    job_id: str
    filename: str
    status: str = "queued"          # queued | parsing | chunking | done | error
    doc_id: str | None = None
    n_pages: int = 0
    n_blocks: int = 0
    n_chunks: int = 0
    error: str | None = None
    n_embedded: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    def as_dict(self) -> dict:
        d = self.__dict__.copy()
        d["elapsed_s"] = round((self.finished_at or time.time()) - self.started_at, 1)
        return d


JOBS: dict[str, Job] = {}
_LOCK = threading.Lock()


def ingest(path: Path, dsn: str, *, title: str, revision: str | None,
           vendor: str | None, equipment_tag: str | None, lang: str, job: Job) -> None:
    try:
        job.status = "parsing"
        suffix = path.suffix.lower()
        blocks = parse_markdown(path) if suffix in (".md", ".markdown") else parse_pdf(path)
        job.n_blocks = len(blocks)
        job.n_pages = len({b.page_no for b in blocks})

        job.status = "chunking"
        chunks = chunk_blocks(blocks, max_chars=MAX_CHARS)
        job.n_chunks = len(chunks)

        doc_id = sha256_of(path)[:16]
        job.doc_id = doc_id

        with psycopg.connect(dsn, autocommit=True) as c:
            c.execute("DELETE FROM document WHERE doc_id=%s", (doc_id,))  # reingesta idempotente
            c.execute(
                """INSERT INTO document
                   (doc_id,title,vendor,equipment_tag,revision,lang,source_path,sha256,n_pages)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                (doc_id, title, vendor, equipment_tag, revision, lang,
                 str(path), sha256_of(path), job.n_pages),
            )
            for b in blocks:
                c.execute(
                    """INSERT INTO page (doc_id,page_no,raw_text,route)
                       VALUES (%s,%s,%s,'fast')
                       ON CONFLICT (doc_id,page_no) DO NOTHING""",
                    (doc_id, b.page_no, b.content[:4000]),
                )
            cfg = {"es": "spanish", "en": "english", "ar": "arabic"}.get(lang, "simple")
            for ch in chunks:
                c.execute(
                    f"""INSERT INTO chunk
                        (doc_id,page_from,page_to,section_path,kind,content,tsv,
                         chunk_strategy_version)
                        VALUES (%s,%s,%s,%s,%s,%s,to_tsvector('{cfg}',%s),%s)""",
                    (doc_id, ch.page_from, ch.page_to, ch.section_path, ch.kind,
                     ch.content, ch.content, STRATEGY_VERSION),
                )
        job.status = "embedding"
        _embed_pending(dsn, job)

        job.status = "done"
    except Exception as e:
        job.status = "error"
        job.error = f"{type(e).__name__}: {e}"
    finally:
        job.finished_at = time.time()


def start_job(path: Path, dsn: str, **meta) -> Job:
    job = Job(job_id=uuid.uuid4().hex[:8], filename=path.name)
    with _LOCK:
        JOBS[job.job_id] = job
    threading.Thread(target=ingest, args=(path, dsn), kwargs={**meta, "job": job},
                     daemon=True).start()
    return job


def _embed_pending(dsn: str, job: Job | None = None) -> int:
    """Calcula embeddings de los chunks que no lo tengan. Idempotente."""
    done = 0
    with psycopg.connect(dsn, autocommit=True) as c:
        rows = c.execute(
            "SELECT chunk_id, content FROM chunk WHERE embedding IS NULL ORDER BY chunk_id"
        ).fetchall()
        if not rows:
            return 0
        ids = [r[0] for r in rows]
        texts = [r[1] for r in rows]
        from anvil.embed.client import BATCH
        for i in range(0, len(texts), BATCH):
            vecs = embed_batched(texts[i : i + BATCH])
            for cid, v in zip(ids[i : i + BATCH], vecs):
                c.execute(
                    "UPDATE chunk SET embedding=%s::vector, embed_model=%s, embed_dim=%s"
                    " WHERE chunk_id=%s",
                    (to_pgvector(v), MODEL, DIM, cid),
                )
            done += len(vecs)
            if job:
                job.n_embedded = done
    return done


def backfill_embeddings(dsn: str) -> Job:
    """Para documentos ya cargados antes de que existiera el embedding."""
    job = Job(job_id=uuid.uuid4().hex[:8], filename="(backfill de embeddings)")
    with _LOCK:
        JOBS[job.job_id] = job

    def run() -> None:
        try:
            job.status = "embedding"
            job.n_embedded = _embed_pending(dsn, job)
            job.status = "done"
        except Exception as e:
            job.status = "error"
            job.error = f"{type(e).__name__}: {e}"
        finally:
            job.finished_at = time.time()

    threading.Thread(target=run, daemon=True).start()
    return job
