"""Verificador determinista (CONTEXTO-ANVIL.md §4).

INVARIANTE: todo numero, codigo de alarma, numero de norma y part number que
aparezca en la respuesta debe aparecer LITERALMENTE en alguno de los chunks
citados. Si no aparece, la respuesta se rechaza.

No es un modelo juzgando a otro modelo: es normalizacion + comparacion de
conjuntos. Es `crew` aplicado a RAG.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# numeros (1.27, 0.50, 680, 9-3), codigos (E-114, H.R. 471, A516), part numbers
_TOKEN = re.compile(
    r"""
      \b[A-Z](?:[-.\s]?[A-Z]){0,4}[-.\s]{0,2}\d{1,6}(?:[-.]\d{1,4})*\b  # H.R. 471, E-114, A516
    | \b\d+(?:[.,]\d+)+\b                             # 1.27, 0.50, 9.5
    | \b\d{1,9}\b                                     # 680, 471, 7
    """,
    re.VERBOSE,
)

# No son afirmaciones de dato del documento: no se verifican.
#  - marcadores de cita [1], [2]  (el modelo los emite para senalar la fuente)
#  - referencias a pagina
_IGNORE_CONTEXT = re.compile(
    r"\[\d+\]|p[aá]g(?:ina)?s?\.?\s*\d+|page\s*\d+", re.IGNORECASE
)


def _normalize(tok: str) -> str:
    """Quita separadores para que 'H.R. 471' y 'H.R.471' sean el mismo dato."""
    return re.sub(r"[\s.\-,]", "", tok).upper()


def extract_facts(text: str) -> set[str]:
    cleaned = _IGNORE_CONTEXT.sub(" ", text)
    return {_normalize(m.group()) for m in _TOKEN.finditer(cleaned)}


@dataclass
class VerdictResult:
    passed: bool
    unsupported: list[str]
    checked: int

    @property
    def reason(self) -> str:
        if self.passed:
            return f"{self.checked} dato(s) verificados contra los documentos citados."
        return (
            "Rechazada: estos datos no aparecen en los documentos citados: "
            + ", ".join(self.unsupported)
        )


def verify(answer: str, cited_texts: list[str]) -> VerdictResult:
    """La respuesta pasa solo si TODOS sus datos estan en el texto citado."""
    supported = set()
    for t in cited_texts:
        supported |= extract_facts(t)

    claimed = extract_facts(answer)
    unsupported = sorted(claimed - supported)
    return VerdictResult(
        passed=not unsupported, unsupported=unsupported, checked=len(claimed)
    )
