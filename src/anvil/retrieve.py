"""Retrieval hibrido: denso (pgvector) + lexico (tsvector), fusionados con RRF.

Por que hibrido (CONTEXTO-ANVIL.md §3, Problema 2): un embedding es busqueda
SEMANTICA. Para el modelo 'E-114', 'E-141' y 'E-115' estan a distancia casi nula,
asi que recuperaria la alarma equivocada. La busqueda lexica captura el codigo
exacto. RRF los combina sin tener que calibrar escalas incompatibles.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import psycopg

from anvil.embed.client import embed, to_pgvector

RRF_K = 60          # constante estandar de Reciprocal Rank Fusion
POOL = 30           # cuantos trae cada rama antes de fusionar

_TS_CFG = {"es": "spanish", "en": "english", "ar": "arabic"}
# codigos tipo E-114, A516, SKF 22320, WPS-014: lo que los embeddings NO distinguen
_CODE = re.compile(r"\b[A-Za-z]{1,4}[-\s]?\d{2,6}\b|\b\d{2,4}[-\s]?[A-Za-z]{1,3}\b")


@dataclass
class Hit:
    chunk_id: int
    doc_id: str
    title: str
    revision: str | None
    superseded_by: str | None
    page_from: int
    page_to: int
    section_path: str | None
    kind: str
    content: str
    score: float
    dense_rank: int | None = None
    lexical_rank: int | None = None


_SELECT = """
  SELECT c.chunk_id, c.doc_id, d.title, d.revision, d.superseded_by,
         c.page_from, c.page_to, c.section_path, c.kind, c.content
  FROM chunk c JOIN document d ON d.doc_id = c.doc_id
"""


def _dense(cur, question: str) -> list[tuple]:
    vec = to_pgvector(embed([question])[0])
    cur.execute(_SELECT + " ORDER BY c.embedding <=> %s::vector LIMIT %s",
                (vec, POOL))
    return cur.fetchall()


_STOP = {"cual","cuales","que","qué","como","cómo","donde","dónde","es","el","la","los",
         "las","de","del","un","una","para","por","en","y","o","a","al","se","su","sus",
         "the","of","is","what","which","where","how","and","or","to","for","in","on"}


def _or_query(question: str) -> str:
    """tsquery con OR: 'stack | trailplugin'.

    plainto_tsquery usa AND, asi que una pregunta natural exige que TODAS sus
    palabras esten en el mismo chunk y no encuentra nada. RRF ya se encarga de
    ordenar: aqui conviene recuperar de mas, no de menos.
    """
    words = [w for w in re.findall(r"[\w.-]{2,}", question.lower())
             if w not in _STOP]
    return " | ".join(w.replace("'", "") for w in words) or "''"


def _lexical(cur, question: str, lang: str) -> list[tuple]:
    cfg = _TS_CFG.get(lang, "simple")
    codes = _CODE.findall(question)
    # los codigos van tambien por ILIKE: el stemmer puede romperlos
    q = _or_query(question)
    if codes:
        like = " OR ".join(["c.content ILIKE %s"] * len(codes))
        cur.execute(
            _SELECT + f" WHERE c.tsv @@ to_tsquery('{cfg}', %s) OR ({like})"
            f" ORDER BY ts_rank(c.tsv, to_tsquery('{cfg}', %s)) DESC LIMIT %s",
            (q, *[f"%{c}%" for c in codes], q, POOL),
        )
    else:
        cur.execute(
            _SELECT + f" WHERE c.tsv @@ to_tsquery('{cfg}', %s)"
            f" ORDER BY ts_rank(c.tsv, to_tsquery('{cfg}', %s)) DESC LIMIT %s",
            (q, q, POOL),
        )
    return cur.fetchall()


def search(dsn: str, question: str, *, lang: str = "en", k: int = 6) -> list[Hit]:
    with psycopg.connect(dsn, autocommit=True) as conn, conn.cursor() as cur:
        try:
            dense = _dense(cur, question)
        except Exception:
            dense = []          # sin Ollama, el lexico sigue sirviendo
        lexical = _lexical(cur, question, lang)

    scores: dict[int, float] = {}
    ranks: dict[int, dict] = {}
    rows: dict[int, tuple] = {}

    for name, result in (("dense_rank", dense), ("lexical_rank", lexical)):
        for i, row in enumerate(result):
            cid = row[0]
            rows[cid] = row
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + i + 1)
            ranks.setdefault(cid, {})[name] = i + 1

    top = sorted(scores, key=lambda c: -scores[c])[:k]
    return [
        Hit(*rows[cid][:10], score=round(scores[cid], 5),
            dense_rank=ranks[cid].get("dense_rank"),
            lexical_rank=ranks[cid].get("lexical_rank"))
        for cid in top
    ]
