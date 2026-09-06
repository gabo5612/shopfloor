"""Chunker estructural — el corazon de shopfloor (CONTEXTO-SHOPFLOOR.md §3, Problema 1).

Una tabla NUNCA se parte sin repetir su encabezado en cada fragmento. Partirla en
silencio hace que el sistema responda 950 N.m donde el valor correcto es 680.
"""

from __future__ import annotations

from shopfloor.parse.types import Chunk, PageBlock

STRATEGY_VERSION = "structural-v1"


def _mk(block: PageBlock, content: str, header: str | None = None) -> Chunk:
    return Chunk(
        page_from=block.page_no,
        page_to=block.page_no,
        kind=block.kind,
        content=content,
        section_path=block.section_path,
        table_header=header,
    )


def _split_table(block: PageBlock, max_chars: int) -> list[Chunk]:
    """Fragmenta filas de datos repitiendo encabezado + separador en cada fragmento.

    Garantiza: (a) cada fragmento tiene >=1 fila; (b) concatenar las filas de los
    fragmentos en orden reproduce exactamente las filas originales.
    """
    lines = block.content.split("\n")
    header, sep, rows = lines[0], lines[1], lines[2:]
    prefix = f"{header}\n{sep}"

    out: list[Chunk] = []
    group: list[str] = []
    for row in rows:
        candidate = group + [row]
        if group and len("\n".join([prefix, *candidate])) > max_chars:
            out.append(_mk(block, "\n".join([prefix, *group]), header))
            group = [row]  # una fila sola puede exceder max_chars: va igual
        else:
            group = candidate
    if group:
        out.append(_mk(block, "\n".join([prefix, *group]), header))
    return out


def _split_lines(block: PageBlock, max_chars: int) -> list[Chunk]:
    """Agrupa lineas enteras sin cortar nunca dentro de una linea."""
    out: list[Chunk] = []
    group: list[str] = []
    for line in block.content.split("\n"):
        candidate = group + [line]
        if group and len("\n".join(candidate)) > max_chars:
            out.append(_mk(block, "\n".join(group)))
            group = [line]
        else:
            group = candidate
    if group:
        out.append(_mk(block, "\n".join(group)))
    return out


def _split_prose(block: PageBlock, max_chars: int) -> list[Chunk]:
    """Corta preferentemente despues de '. '; nunca excede max_chars."""
    out: list[Chunk] = []
    rest = block.content
    while len(rest) > max_chars:
        window = rest[:max_chars]
        cut = window.rfind(". ")
        cut = cut + 2 if cut != -1 else max_chars
        piece = rest[:cut].strip()
        if piece:
            out.append(_mk(block, piece))
        rest = rest[cut:]
    tail = rest.strip()
    if tail:
        out.append(_mk(block, tail))
    return out


def chunk_blocks(blocks: list[PageBlock], max_chars: int) -> list[Chunk]:
    """Convierte bloques parseados en chunks indexables, respetando su estructura."""
    out: list[Chunk] = []
    for block in blocks:
        if not block.content.strip():
            continue

        if len(block.content) <= max_chars:
            header = block.content.split("\n")[0] if block.kind == "table" else None
            out.append(_mk(block, block.content, header))
        elif block.kind == "table":
            out.extend(_split_table(block, max_chars))
        elif block.kind == "procedure":
            out.extend(_split_lines(block, max_chars))
        else:
            out.extend(_split_prose(block, max_chars))
    return out
