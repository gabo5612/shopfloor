"""Generacion con citas usando un modelo local (Ollama).

El modelo REDACTA. No decide. Todo dato numerico que produzca pasa por el
verificador determinista (anvil/verify.py) antes de llegar al usuario.
"""

from __future__ import annotations

import json
import os
import urllib.request
from dataclasses import dataclass

from anvil.retrieve import Hit
from anvil.verify import VerdictResult, verify

MODEL = os.environ.get("ANVIL_GEN_MODEL", "qwen2.5-coder:7b")
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MAX_RETRY = 1
ABSTAIN = "NO_ESTA_EN_LA_DOCUMENTACION"

SYSTEM = f"""Eres un asistente de documentacion tecnica de una planta industrial.

REGLAS ABSOLUTAS:
1. Responde UNICAMENTE con informacion presente en los PASAJES entregados.
2. Copia los numeros, codigos y referencias EXACTAMENTE como aparecen. Nunca los
   redondees, conviertas ni estimes.
3. Si los pasajes no contienen la respuesta, responde exactamente: {ABSTAIN}
4. No uses conocimiento propio. No inventes. No completes lo que falta.
5. Responde en el idioma de la pregunta, de forma breve y directa.
6. Cita el pasaje con [n] donde n es su numero."""


@dataclass
class Generated:
    answer: str | None
    abstained: bool
    verdict: VerdictResult | None
    retries: int
    model: str


def _call(messages: list[dict], timeout: int = 300) -> str:
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat",
        data=json.dumps({
            "model": MODEL, "messages": messages, "stream": False,
            "options": {"temperature": 0},   # determinista: es documentacion, no creatividad
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["message"]["content"].strip()


def _passages(hits: list[Hit]) -> str:
    return "\n\n".join(
        f"[{i}] ({h.title}"
        + (f", Rev {h.revision}" if h.revision else "")
        + f", pag. {h.page_from}) {h.content}"
        for i, h in enumerate(hits, 1)
    )


def answer_question(question: str, hits: list[Hit], *, lang: str = "es") -> Generated:
    if not hits:
        return Generated(None, True, None, 0, MODEL)

    prompt = f"PASAJES:\n{_passages(hits)}\n\nPREGUNTA: {question}"
    texts = [h.content for h in hits]
    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": prompt}]

    for attempt in range(MAX_RETRY + 1):
        raw = _call(messages)

        if ABSTAIN in raw or not raw:
            return Generated(None, True, None, attempt, MODEL)

        verdict = verify(raw, texts)
        if verdict.passed:
            return Generated(raw, False, verdict, attempt, MODEL)

        if attempt < MAX_RETRY:
            # feedback determinista al modelo: le decimos QUE dato invento
            messages += [
                {"role": "assistant", "content": raw},
                {"role": "user", "content":
                 "Estos datos NO aparecen en los pasajes: "
                 + ", ".join(verdict.unsupported)
                 + f". Reescribe usando solo datos de los pasajes, o responde {ABSTAIN}."},
            ]

    # se agotaron los intentos: abstenerse es mejor que entregar un dato inventado
    return Generated(None, True, verdict, MAX_RETRY, MODEL)
