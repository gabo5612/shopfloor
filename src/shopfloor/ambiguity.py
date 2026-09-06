"""Deteccion DETERMINISTA de ambiguedad en tablas.

Por que no se lo pedimos al modelo: medido sobre la Tabla 4-7, ante
"torque del perno M24" el modelo elige 680 y responde con total confianza,
sin notar que existe otra fila M24 con 950. Delegarle esa decision es
justamente lo que este proyecto no hace.

Aqui la ambiguedad se detecta con operaciones sobre la tabla:
si >1 fila coincide con lo que pide la pregunta y sus valores difieren,
falta un criterio -> hay que preguntar, no elegir.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SPLIT = re.compile(r"\s*\|\s*")
_SEP_ROW = re.compile(r"^[\s|:-]+$")
# terminos con los que un usuario identifica una fila: M24, A516, E-114, 8.8
_TERM = re.compile(r"[A-Za-z]{1,5}[-.]?\d+(?:[.,]\d+)?|\d+(?:[.,]\d+)?")


@dataclass
class Table:
    header: list[str]
    rows: list[list[str]]


@dataclass
class Ambiguity:
    question: str
    options: list[str]
    column: str


def parse_markdown_tables(text: str) -> list[Table]:
    tables: list[Table] = []
    header: list[str] | None = None
    rows: list[list[str]] = []

    def flush() -> None:
        nonlocal header, rows
        if header and rows:
            tables.append(Table(header, rows))
        header, rows = None, []

    for line in text.splitlines():
        if "|" not in line:
            flush()
            continue
        cells = [c.strip() for c in _SPLIT.split(line.strip().strip("|"))]
        if _SEP_ROW.match(line):
            continue
        if header is None:
            header = cells
        else:
            rows.append(cells)
    flush()
    return tables


def _terms(text: str) -> set[str]:
    return {t.lower().replace(",", ".") for t in _TERM.findall(text)}


def detect(question: str, chunks: list[str]) -> Ambiguity | None:
    """Devuelve la pregunta a hacer, o None si no hay ambiguedad real."""
    q_terms = _terms(question)
    if not q_terms:
        return None

    for chunk in chunks:
        for tbl in parse_markdown_tables(chunk):
            ncol = len(tbl.header)
            # Solo compiten las filas que MEJOR coinciden con la pregunta.
            # "M24 grado 8.8" coincide en 2 terminos con su fila y en 1 con las
            # otras: gana una sola fila y no hay ambiguedad. "M24" coincide en 1
            # con dos filas: empatan, y ahi si falta un criterio.
            scored = [
                (len(q_terms & _terms(" ".join(r))), r)
                for r in tbl.rows if len(r) == ncol
            ]
            best = max((n for n, _ in scored), default=0)
            if best == 0:
                continue
            matches = [r for n, r in scored if n == best]
            if len(matches) < 2:
                continue

            # Una columna desambigua si sus valores difieren entre las filas
            # empatadas, la pregunta no menciona ninguno, y alguna OTRA columna
            # tambien difiere (si el resto es igual, las filas dicen lo mismo).
            # Heuristica: se toma la PRIMERA columna que cumple, porque en una
            # tabla de consulta las columnas clave preceden a las de resultado.
            for i in range(ncol):
                vals = [r[i] for r in matches]
                uniq = list(dict.fromkeys(vals))
                if len(uniq) < 2:
                    continue
                if q_terms & _terms(" ".join(uniq)):
                    continue  # la pregunta ya fija este criterio
                others_differ = any(
                    len({r[j] for r in matches}) > 1
                    for j in range(ncol) if j != i
                )
                if not others_differ:
                    continue
                col = tbl.header[i] or f"columna {i+1}"
                return Ambiguity(
                    question=f"¿Para qué {col.lower()}?",
                    options=uniq,
                    column=col,
                )
    return None
