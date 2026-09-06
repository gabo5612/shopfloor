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
_NUM = re.compile(r"^\d+(?:[.,]\d+)?$")

# Comparadores que eligen UN LADO de un limite. Sin esto "hasta 20" y "mas de
# 20" se reducen al mismo termino {20}: las palabras que separan las dos filas
# son invisibles, la columna que de verdad discrimina parece una que la
# pregunta ya fijo, y el detector cae en la columna de RESULTADO — le pregunta
# al usuario cual de las dos respuestas queria. Medido sobre la tabla de
# precalentamiento: "A516 Gr.70 en espesores mayores a 20 mm" devolvia
# "¿Para que precalentamiento?" con opciones ['ninguno', '95'].
_GT = re.compile(
    r"m[aá]s de|mayor(?:es)?\s+(?:a|que|de)|superior(?:es)?\s+a|arriba de|encima de"
    r"|por encima de|over|more than|greater than|above|>=|>|≥",
    re.I,
)
_LT = re.compile(
    r"hasta|menos de|menor(?:es)?\s+(?:a|que|de)|inferior(?:es)?\s+a|por debajo de"
    r"|up to|under|less than|below|<=|<|≤",
    re.I,
)
# Un limite inclusivo incluye su propio numero: "hasta 20" cubre el 20,
# "menos de 20" no. La diferencia decide si un espesor de 20 mm cae en una
# fila o en la otra, asi que no se puede aproximar.
_INCLUSIVE = re.compile(r"hasta|up to|al menos|at least|>=|<=|≥|≤|o m[aá]s|o menos", re.I)
_ANY = re.compile(r"^\s*(cualquiera|cualquier|todos|todas|any|all|-{1,2}|n/?a)\s*$", re.I)
_RANGE = re.compile(
    r"^\s*(\d+(?:[.,]\d+)?)\s*(?:-|–|a|to|hasta)\s*(\d+(?:[.,]\d+)?)\s*$", re.I
)


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
    """Terminos que identifican una fila, incluido el LADO de un limite.

    El marcador `>` o `<` entra al conjunto como un termino mas, para que
    "espesores mayores a 20" puntue mejor contra "mas de 20" que contra
    "hasta 20" y la fila correcta gane sola, sin preguntar nada.
    """
    out = {t.lower().replace(",", ".") for t in _TERM.findall(text)}
    out |= _bounds(text)
    return out


def _bounds(text: str) -> set[str]:
    out: set[str] = set()
    if _GT.search(text):
        out.add(">")
    if _LT.search(text):
        out.add("<")
    return out


def _as_number(token: str) -> float | None:
    if not _NUM.match(token):
        return None
    return float(token.replace(",", "."))


def _point_values(question: str) -> list[float]:
    """Numeros SUELTOS de la pregunta: "15 mm" da 15; "A516" y "Gr.70" no.

    Solo cuentan si la pregunta no trae comparador: "mayores a 20" no es el
    punto 20, es el intervalo abierto que empieza en 20, y ese caso ya lo
    resuelve el puntaje por terminos.
    """
    if _bounds(question):
        return []
    vals = []
    for t in _TERM.findall(question):
        n = _as_number(t)
        if n is not None:
            vals.append(n)
    return vals


def _covers(cell: str) -> "callable[[float], bool] | None":
    """Traduce una celda de intervalo a un predicado. None = no es intervalo.

    Si UNA celda de la columna no se puede leer, la columna entera se deja
    en paz: adivinar el intervalo de una celda que no se entendio es peor que
    preguntar de mas.
    """
    cell = cell.strip()
    if not cell:
        return None
    if _ANY.match(cell):
        return lambda _x: True

    m = _RANGE.match(cell)
    if m:
        lo, hi = (float(g.replace(",", ".")) for g in m.groups())
        return lambda x, lo=lo, hi=hi: lo <= x <= hi

    nums = [n for n in (_as_number(t) for t in _TERM.findall(cell)) if n is not None]
    if len(nums) != 1:
        return None
    n = nums[0]
    inclusive = bool(_INCLUSIVE.search(cell))
    if _GT.search(cell):
        return (lambda x, n=n: x >= n) if inclusive else (lambda x, n=n: x > n)
    if _LT.search(cell):
        return (lambda x, n=n: x <= n) if inclusive else (lambda x, n=n: x < n)
    if cell == str(int(n)) or cell == str(n):
        return lambda x, n=n: x == n
    return None


def _narrow_by_ranges(question: str, matches: list[list[str]], ncol: int) -> list[list[str]]:
    """Descarta las filas cuyo intervalo NO contiene el valor de la pregunta.

    "A516 Gr.70 de 15 mm" empataba con las dos filas del material porque el
    15 no se comparaba contra nada: 15 cae en "hasta 20" y no cae en "mas de
    20", asi que sobra una sola fila y no hay nada que preguntar.
    """
    points = _point_values(question)
    if not points:
        return matches
    for i in range(ncol):
        preds = [_covers(r[i]) for r in matches]
        if any(p is None for p in preds):
            continue  # columna no legible como intervalo: no se toca
        survivors = [
            r for r, p in zip(matches, preds) if any(p(x) for x in points)
        ]
        if 1 <= len(survivors) < len(matches):
            matches = survivors
    return matches


def _answerable(column: str, options: list[str]) -> bool:
    """¿Es contestable la repregunta que estamos por hacer?

    Medido contra el TM de 117 paginas: una lista de repuestos que el parser
    lee como tabla producia "¿Para que (1) item no.?" con opciones ['', '1'],
    y "¿Para que 04?" — el encabezado era el numero de fila. Una repregunta
    con una opcion vacia, o cuya columna no tiene nombre, no la puede
    contestar nadie: el sistema queda mudo sin salida. Ante eso conviene
    intentar responder — la respuesta todavia pasa por groundedness y por el
    verificador — antes que bloquear al tecnico con una pregunta imposible.
    """
    if not any(c.isalpha() for c in column):
        return False
    opts = [o.strip() for o in options]
    if any(not o for o in opts):
        return False
    return len(set(opts)) >= 2


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

            # Si la pregunta trae un valor puntual, las filas cuyo intervalo no
            # lo contiene quedan fuera. Va ANTES del barrido de columnas: si el
            # valor deja una sola fila en pie, no hay ambiguedad que reportar.
            matches = _narrow_by_ranges(question, matches, ncol)
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
                if not _answerable(col, uniq):
                    continue
                return Ambiguity(
                    question=f"¿Para qué {col.lower()}?",
                    options=uniq,
                    column=col,
                )
    return None
