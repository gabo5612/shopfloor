"""Tipos del pipeline de parseo. Escrito por el arquitecto: es el contrato
que consumen el parser, el chunker y el indexador. No lo modifiquen los obreros."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

BlockKind = Literal["prose", "table", "procedure", "heading"]


@dataclass(frozen=True)
class PageBlock:
    """Un bloque de contenido con su pagina de origen SIEMPRE presente.

    INVARIANTE: page_no nunca es None. Sin pagina no hay cita verificable,
    y sin cita verificable no existe el verificador determinista (§4).
    page_no es 1-indexado, como lo ve un humano en el visor de PDF.
    """

    page_no: int
    kind: BlockKind
    content: str
    section_path: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.page_no, int) or self.page_no < 1:
            raise ValueError(f"page_no debe ser entero >= 1, recibido: {self.page_no!r}")


@dataclass(frozen=True)
class Chunk:
    """Unidad indexable. Puede abarcar varias paginas (page_from..page_to)."""

    page_from: int
    page_to: int
    kind: BlockKind
    content: str
    section_path: str | None = None
    table_header: str | None = None  # si es un fragmento de tabla, su encabezado repetido

    def __post_init__(self) -> None:
        if self.page_from < 1 or self.page_to < self.page_from:
            raise ValueError(f"rango de paginas invalido: {self.page_from}..{self.page_to}")
