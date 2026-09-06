"""Embeddings locales via Ollama.

INVARIANTE: ingesta y retrieval DEBEN usar el mismo modelo y la misma dimension,
o la distancia coseno no significa nada. Ambos importan MODEL y DIM de aqui,
por esa razon. No hardcodear el nombre del modelo en ningun otro archivo.
"""

from __future__ import annotations

import json
import os
import urllib.request

MODEL = os.environ.get("SHOPFLOOR_EMBED_MODEL", "bge-m3")
DIM = 1024                      # bge-m3: hidden_size verificado = 1024
BATCH = 32                      # medido: 3.3x mas rapido que batch=1
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")


def embed(texts: list[str], *, timeout: int = 600) -> list[list[float]]:
    """Devuelve un vector por texto, en el mismo orden."""
    if not texts:
        return []
    req = urllib.request.Request(
        f"{OLLAMA}/api/embed",
        data=json.dumps({"model": MODEL, "input": texts}).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        out = json.load(r)["embeddings"]
    if out and len(out[0]) != DIM:
        raise RuntimeError(
            f"dimension inesperada: {len(out[0])} != {DIM}. "
            "El indice quedaria inconsistente; se aborta."
        )
    return out


def embed_batched(texts: list[str], *, on_progress=None) -> list[list[float]]:
    vecs: list[list[float]] = []
    for i in range(0, len(texts), BATCH):
        vecs.extend(embed(texts[i : i + BATCH]))
        if on_progress:
            on_progress(len(vecs), len(texts))
    return vecs


def to_pgvector(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"
