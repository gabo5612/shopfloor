"""Cache semantico de preguntas ya respondidas.

MEDIDO ANTES DE DISENARLO (2026-09-02, bge-m3):

    0.8431  "torque de apriete del M24 grado 8.8"      -> misma respuesta (680)
    0.9089  "torque del perno M24 grado 10.9"          -> respuesta DISTINTA (950)

La pregunta con respuesta distinta se parece MAS que la reformulacion legitima.
Un cache por similitud sola serviria 680 a quien pregunto por el grado 10.9.

Por eso un acierto exige DOS condiciones:
  1. similitud coseno >= SIM_MIN
  2. MISMO conjunto de terminos tecnicos (M24, 8.8, E-114) -- comparacion exacta

Y ademas se refresca solo: si el contenido de los chunks citados cambia
(revision nueva del manual), el hash no coincide, la entrada se marca STALE y
se vuelve a responder contra la revision vigente. No se borra: la pregunta que
alguien se tomo el trabajo de hacer es dato valioso, y ademas es la semilla
natural del golden set de evals.

Servir la respuesta de una Rev D cuando ya rige la Rev E es el fallo peligroso;
por eso una entrada stale NUNCA se sirve mientras espera su refresco.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

import psycopg

from shopfloor.embed.client import embed, to_pgvector

SIM_MIN = 0.80          # por debajo de la reformulacion legitima medida (0.8431)
POOL = 5

_TERM = re.compile(r"[A-Za-z]{1,6}[-.]?\d+(?:[.,]\d+)?|\b\d+(?:[.,]\d+)?\b")


def terms_of(question: str) -> list[str]:
    """Terminos que identifican QUE se pregunta. Su igualdad es obligatoria."""
    return sorted({t.lower().replace(",", ".") for t in _TERM.findall(question)})


def hash_chunks(rows: list[tuple[int, str]]) -> str:
    h = hashlib.sha256()
    for cid, content in sorted(rows):
        h.update(str(cid).encode())
        h.update(content.encode())
    return h.hexdigest()


@dataclass
class CacheHit:
    cache_id: int
    answer: str
    question: str
    similarity: float
    chunk_ids: list[int]
    hits: int
    confirmed: bool | None


def lookup(dsn: str, question: str, lang: str) -> CacheHit | None:
    vec = to_pgvector(embed([question])[0])
    want = terms_of(question)

    with psycopg.connect(dsn, autocommit=True) as c:
        rows = c.execute(
            """SELECT cache_id, question, answer, chunk_ids, content_hash,
                      hits, confirmed, terms, stale,
                      1 - (embedding <=> %s::vector)
               FROM qa_cache WHERE lang = %s
               ORDER BY embedding <=> %s::vector LIMIT %s""",
            (vec, lang, vec, POOL),
        ).fetchall()

        for cid, q, ans, chunk_ids, chash, hits, confirmed, terms, stale, sim in rows:
            if stale:
                continue                                # esperando refresco
            if sim < SIM_MIN:
                break                                   # vienen ordenados
            if list(terms) != want:
                continue                                # guard determinista
            if confirmed is False:
                continue                                # el usuario la rechazo

            current = c.execute(
                "SELECT chunk_id, content FROM chunk WHERE chunk_id = ANY(%s)",
                (chunk_ids,),
            ).fetchall()
            if len(current) != len(chunk_ids) or hash_chunks(current) != chash:
                # El documento cambio: no se sirve, pero TAMPOCO se borra.
                # Queda marcada para re-responderse contra la revision vigente.
                c.execute(
                    "UPDATE qa_cache SET stale = true WHERE cache_id = %s", (cid,)
                )
                continue

            c.execute(
                "UPDATE qa_cache SET hits = hits + 1, last_used_at = now()"
                " WHERE cache_id = %s", (cid,),
            )
            return CacheHit(cid, ans, q, round(float(sim), 4),
                            list(chunk_ids), hits + 1, confirmed)
    return None


def store(dsn: str, question: str, lang: str, answer: str,
          chunk_ids: list[int]) -> None:
    if not chunk_ids:
        return
    vec = to_pgvector(embed([question])[0])
    with psycopg.connect(dsn, autocommit=True) as c:
        rows = c.execute(
            "SELECT chunk_id, content FROM chunk WHERE chunk_id = ANY(%s)",
            (chunk_ids,),
        ).fetchall()
        if not rows:
            return
        c.execute(
            """INSERT INTO qa_cache
               (question, lang, embedding, terms, answer, chunk_ids,
                content_hash, doc_ids)
               VALUES (%s,%s,%s::vector,%s,%s,%s,%s,
                       (SELECT array_agg(DISTINCT doc_id) FROM chunk
                        WHERE chunk_id = ANY(%s)))""",
            (question, lang, vec, terms_of(question), answer,
             chunk_ids, hash_chunks(rows), chunk_ids),
        )


def set_confirmed(dsn: str, cache_id: int, ok: bool) -> None:
    with psycopg.connect(dsn, autocommit=True) as c:
        if ok:
            c.execute("UPDATE qa_cache SET confirmed = true WHERE cache_id = %s",
                      (cache_id,))
        else:
            c.execute("DELETE FROM qa_cache WHERE cache_id = %s", (cache_id,))


def mark_stale_for_doc(dsn: str, doc_id: str) -> int:
    """Marca para refresco toda respuesta que cito ese documento."""
    with psycopg.connect(dsn, autocommit=True) as c:
        return c.execute(
            "UPDATE qa_cache SET stale = true WHERE %s = ANY(doc_ids)"
            " AND stale = false", (doc_id,),
        ).rowcount


def mark_dangling_stale(dsn: str) -> int:
    """Marca las entradas cuyos chunks citados ya no existen.

    Pasa cuando un documento se reemplaza por una revision nueva: el archivo
    cambia, su doc_id cambia, y los chunks viejos desaparecen. Comprobar el
    doc_id no alcanza; hay que mirar si los chunks siguen ahi.
    """
    with psycopg.connect(dsn, autocommit=True) as c:
        return c.execute(
            """UPDATE qa_cache SET stale = true
               WHERE stale = false AND EXISTS (
                 SELECT 1 FROM unnest(chunk_ids) AS cid
                 WHERE NOT EXISTS (SELECT 1 FROM chunk WHERE chunk_id = cid))"""
        ).rowcount


def stale_entries(dsn: str) -> list[tuple[int, str, str]]:
    with psycopg.connect(dsn, autocommit=True) as c:
        return c.execute(
            "SELECT cache_id, question, lang FROM qa_cache"
            " WHERE stale ORDER BY hits DESC, cache_id"
        ).fetchall()


def update_answer(dsn: str, cache_id: int, answer: str | None,
                  chunk_ids: list[int]) -> None:
    """Guarda la respuesta re-generada contra la revision vigente."""
    with psycopg.connect(dsn, autocommit=True) as c:
        if not answer or not chunk_ids:
            # La revision nueva ya no responde esa pregunta: se conserva la
            # entrada (la pregunta sigue siendo dato) pero no se sirve.
            c.execute(
                "UPDATE qa_cache SET refreshed_at = now(), confirmed = NULL"
                " WHERE cache_id = %s", (cache_id,),
            )
            return
        rows = c.execute(
            "SELECT chunk_id, content FROM chunk WHERE chunk_id = ANY(%s)",
            (chunk_ids,),
        ).fetchall()
        c.execute(
            """UPDATE qa_cache SET answer=%s, chunk_ids=%s, content_hash=%s,
                   stale=false, refreshed_at=now(), confirmed=NULL,
                   doc_ids=(SELECT array_agg(DISTINCT doc_id) FROM chunk
                            WHERE chunk_id = ANY(%s))
               WHERE cache_id=%s""",
            (answer, chunk_ids, hash_chunks(rows), chunk_ids, cache_id),
        )
