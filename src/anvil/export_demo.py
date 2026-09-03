"""Exporta un paquete estatico del corpus para una demo sin servidor.

Que se lleva y que NO:
  SI  chunks con su documento, revision, pagina y seccion  -> busqueda lexica
  SI  respuestas ya generadas por el modelo local          -> se muestran tal cual
  NO  embeddings                                            -> sin modelo no hay
      forma de embeber la pregunta del visitante en el navegador

La demo es honesta sobre eso: dice que corre solo la mitad lexica.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import psycopg

DSN = "postgresql://anvil:anvil@localhost:5433/anvil"
STOP = {
    "cual", "cuales", "que", "como", "donde", "es", "el", "la", "los", "las",
    "de", "del", "un", "una", "para", "por", "en", "y", "o", "a", "al", "se",
    "su", "sus", "the", "of", "is", "what", "which", "where", "how", "and",
    "or", "to", "for", "in", "on", "with",
}
_W = re.compile(r"[\w.-]{2,}")


def tokens(text: str) -> list[str]:
    return [w for w in _W.findall(text.lower()) if w not in STOP]


def export(out: Path) -> dict:
    with psycopg.connect(DSN, autocommit=True) as c:
        docs = c.execute(
            """SELECT doc_id, title, revision, vendor, equipment_tag, lang, n_pages
               FROM document ORDER BY title"""
        ).fetchall()
        chunks = c.execute(
            """SELECT chunk_id, doc_id, page_from, page_to, section_path, kind, content
               FROM chunk ORDER BY chunk_id"""
        ).fetchall()
        cache = c.execute(
            """SELECT question, lang, terms, answer, chunk_ids, hits, confirmed
               FROM qa_cache WHERE stale = false AND answer <> '' ORDER BY hits DESC"""
        ).fetchall()

    # indice invertido: token -> [indices de chunk]. Evita recorrer 1689 textos.
    index: dict[str, list[int]] = {}
    for i, ch in enumerate(chunks):
        seen = set(tokens((ch[4] or "") + " " + ch[6]))
        for t in seen:
            index.setdefault(t, []).append(i)

    data = {
        "generated_at": __import__("datetime").datetime.now().isoformat(timespec="seconds"),
        "docs": [
            {"doc_id": d[0], "title": d[1], "revision": d[2], "vendor": d[3],
             "tag": d[4], "lang": d[5], "pages": d[6]}
            for d in docs
        ],
        "chunks": [
            {"id": ch[0], "doc": ch[1], "p0": ch[2], "p1": ch[3],
             "sec": ch[4], "kind": ch[5], "text": ch[6]}
            for ch in chunks
        ],
        "index": index,
        "cache": [
            {"q": q, "lang": lang, "terms": list(terms), "a": ans,
             "chunk_ids": list(cids), "hits": hits, "confirmed": conf}
            for q, lang, terms, ans, cids, hits, conf in cache
        ],
    }
    out.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                   encoding="utf-8")
    return {"docs": len(docs), "chunks": len(chunks), "cache": len(cache),
            "tokens": len(index), "kb": round(out.stat().st_size / 1024)}


if __name__ == "__main__":
    print(export(Path(__file__).resolve().parents[2] / "demo" / "corpus.json"))
