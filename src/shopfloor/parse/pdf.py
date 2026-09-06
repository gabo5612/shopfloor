"""PDF -> list[PageBlock] conservando SIEMPRE el numero de pagina.

Decision (CONTEXTO-SHOPFLOOR.md §7.1-7.3): se usa docling porque conserva pagina,
extrae tablas y trae OCR local. Medido: 754 ms/pag con modelos cacheados.
markitdown es ~30x mas rapido pero descarta el numero de pagina, que es el
requisito central de shopfloor.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from shopfloor.parse.types import BlockKind, PageBlock

_KIND_BY_LABEL: dict[str, BlockKind] = {
    "table": "table",
    "section_header": "heading",
    "title": "heading",
    "list_item": "procedure",
    "text": "prose",
    "paragraph": "prose",
    "caption": "prose",
}


def sha256_of(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _page_of(item) -> int | None:
    prov = getattr(item, "prov", None) or []
    for p in prov:
        page = getattr(p, "page_no", None)
        if isinstance(page, int) and page >= 1:
            return page
    return None


def parse_pdf(path: str | Path) -> list[PageBlock]:
    """Devuelve bloques con pagina. Los items sin pagina se DESCARTAN.

    INVARIANTE: nunca se emite un bloque sin pagina. Sin pagina no hay cita
    verificable, y sin cita no existe el verificador determinista (§4).
    """
    from docling.document_converter import DocumentConverter

    doc = DocumentConverter().convert(str(path)).document

    blocks: list[PageBlock] = []
    section: str | None = None

    for item, _level in doc.iterate_items():
        label = str(getattr(item, "label", "") or "").lower()
        kind = _KIND_BY_LABEL.get(label, "prose")

        if label in ("table",) or type(item).__name__ == "TableItem":
            kind = "table"
            try:
                content = item.export_to_markdown(doc)
            except TypeError:
                content = item.export_to_markdown()
        else:
            content = getattr(item, "text", "") or ""

        if not content.strip():
            continue

        page = _page_of(item)
        if page is None:
            continue  # sin pagina no entra al indice

        if kind == "heading":
            section = content.strip()

        blocks.append(
            PageBlock(page_no=page, kind=kind, content=content, section_path=section)
        )

    return blocks
