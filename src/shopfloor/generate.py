"""Generacion con citas, clarificacion y verificacion (local, via Ollama).

Flujo (CONTEXTO-SHOPFLOOR.md §3-§4):

    pasajes -> el modelo TRIA en 3 salidas posibles
                 ANSWER   : los pasajes responden sin ambiguedad
                 CLARIFY  : hay >1 respuesta valida segun un criterio que la
                            pregunta no fija -> se PREGUNTA en vez de adivinar
                 ABSTAIN  : la respuesta no esta en los pasajes
             -> verificador determinista sobre la respuesta Y sobre las opciones

Por que CLARIFY existe: la Tabla 4-7 tiene M24 grado 8.8 -> 680 N.m y M24
grado 10.9 -> 950 N.m. Ante "torque del M24" la respuesta correcta NO es
elegir una: es preguntar el grado. Adivinar es un perno estirado.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass, field

from shopfloor.ambiguity import detect as detect_ambiguity
from shopfloor.retrieve import Hit
from shopfloor.verify import VerdictResult, verify

MODEL = os.environ.get("SHOPFLOOR_GEN_MODEL", "qwen2.5-coder:7b")
OLLAMA = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
MAX_RETRY = 1

SYSTEM = """Eres un asistente de documentacion tecnica de una planta industrial.
Respondes SOLO con lo que dicen los PASAJES. Devuelves JSON valido, nada mas.

Elige UNO de estos tres formatos:

1) Si los pasajes responden la pregunta sin ambiguedad:
{"status":"answer","answer":"respuesta breve terminada en el numero de pasaje entre corchetes, por ejemplo: 680 +/- 30 N.m [1]"}

2) Si hay MAS DE UNA respuesta valida en los pasajes porque la pregunta no
   especifica un criterio (grado del perno, espesor, modelo, revision, etc.):
{"status":"clarify","question":"la pregunta que hace falta","options":["valor 1","valor 2"]}

3) Si los pasajes NO contienen la respuesta:
{"status":"abstain"}

REGLAS ABSOLUTAS:
- Copia numeros y codigos EXACTAMENTE como aparecen en los pasajes.
- Las opciones de "clarify" deben ser valores que aparecen en los pasajes.
- Nunca uses conocimiento propio. Nunca estimes ni redondees.
- Responde en el idioma de la pregunta."""


@dataclass
class Generated:
    answer: str | None = None
    abstained: bool = False
    needs_clarification: bool = False
    clarify_question: str | None = None
    options: list[str] = field(default_factory=list)
    verdict: VerdictResult | None = None
    retries: int = 0
    model: str = MODEL


def _call(messages: list[dict], timeout: int = 300) -> str:
    req = urllib.request.Request(
        f"{OLLAMA}/api/chat",
        data=json.dumps({
            "model": MODEL, "messages": messages, "stream": False,
            "format": "json",                    # Ollama fuerza JSON valido
            "options": {"temperature": 0},       # documentacion, no creatividad
        }).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["message"]["content"].strip()


def _parse(raw: str) -> dict:
    try:
        d = json.loads(raw)
        return d if isinstance(d, dict) else {}
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", raw, re.S)
        try:
            return json.loads(m.group()) if m else {}
        except json.JSONDecodeError:
            return {}


def _passages(hits: list[Hit]) -> str:
    return "\n\n".join(
        f"[{i}] ({h.title}" + (f", Rev {h.revision}" if h.revision else "")
        + f", pag. {h.page_from}) {h.content}"
        for i, h in enumerate(hits, 1)
    )


def answer_question(question: str, hits: list[Hit], *, lang: str = "es") -> Generated:
    if not hits:
        return Generated(abstained=True)

    texts = [h.content for h in hits]

    # La ambiguedad se detecta ANTES de llamar al modelo, y de forma
    # determinista: medido, el modelo elige 680 sin notar que existe 950.
    amb = detect_ambiguity(question, texts)
    if amb:
        return Generated(
            needs_clarification=True,
            clarify_question=amb.question,
            options=amb.options,
            verdict=verify(" ".join(amb.options), texts),
        )

    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": f"PASAJES:\n{_passages(hits)}\n\nPREGUNTA: {question}"},
    ]

    verdict: VerdictResult | None = None
    for attempt in range(MAX_RETRY + 1):
        d = _parse(_call(messages))
        status = d.get("status")

        if status == "abstain" or not status:
            return Generated(abstained=True, retries=attempt)

        if status == "clarify":
            opts = [str(o) for o in (d.get("options") or []) if str(o).strip()]
            # las opciones tambien se verifican: no puede ofrecer un grado inexistente
            v = verify(" ".join(opts), texts)
            if v.passed and len(opts) >= 2:
                return Generated(
                    needs_clarification=True,
                    clarify_question=str(d.get("question") or "").strip()
                    or "Falta un dato para responder con precision.",
                    options=opts, verdict=v, retries=attempt,
                )
            verdict = v  # opciones inventadas: cae al reintento

        elif status == "answer":
            ans = str(d.get("answer") or "").strip()
            if ans:
                verdict = verify(ans, texts)
                if verdict.passed:
                    return Generated(answer=ans, verdict=verdict, retries=attempt)

        if attempt < MAX_RETRY and verdict is not None:
            messages += [
                {"role": "assistant", "content": json.dumps(d)},
                {"role": "user", "content":
                 "Estos datos NO aparecen en los pasajes: "
                 + ", ".join(verdict.unsupported)
                 + '. Corrige usando solo datos de los pasajes, o devuelve {"status":"abstain"}.'},
            ]

    return Generated(abstained=True, verdict=verdict, retries=MAX_RETRY)
