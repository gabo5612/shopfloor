"""Markdown -> list[PageBlock].

Un .md no tiene paginas. Se pagina por CABECERA de nivel 1-2: cada seccion es
una "pagina" numerada en orden de aparicion, para que la cita siga siendo
verificable y apunte a algo que el lector pueda encontrar.

El invariante de shopfloor se mantiene: nunca se emite un bloque sin page_no.
"""

from __future__ import annotations

import re
from pathlib import Path

from shopfloor.parse.types import PageBlock

_H = re.compile(r"^(#{1,6})\s+(.*)$")
_TABLE_ROW = re.compile(r"^\s*\|.*\|\s*$")
_LIST_ITEM = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+")
_FENCE = re.compile(r"^\s*(```|~~~)")


def parse_markdown(path: str | Path) -> list[PageBlock]:
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    blocks: list[PageBlock] = []
    page = 1
    section: str | None = None
    buf: list[str] = []
    mode = "prose"          # prose | table | procedure | code
    fence: str | None = None

    def flush() -> None:
        nonlocal buf, mode
        content = "\n".join(buf).strip()
        if content:
            kind = {"table": "table", "procedure": "procedure",
                    "code": "prose"}.get(mode, "prose")
            blocks.append(PageBlock(page_no=page, kind=kind, content=content,
                                    section_path=section))
        buf, mode = [], "prose"

    for line in lines:
        f = _FENCE.match(line)
        if f:                                  # dentro de ``` nada se interpreta
            if fence is None:
                flush()
                fence, mode = f.group(1), "code"
            elif line.strip().startswith(fence):
                buf.append(line)
                flush()
                fence = None
                continue
            buf.append(line)
            continue
        if fence is not None:
            buf.append(line)
            continue

        h = _H.match(line)
        if h:
            flush()
            level, title = len(h.group(1)), h.group(2).strip()
            if level <= 2 and blocks:
                page += 1                      # nueva "pagina" por seccion mayor
            section = title
            blocks.append(PageBlock(page_no=page, kind="heading", content=title,
                                    section_path=section))
            continue

        want = ("table" if _TABLE_ROW.match(line)
                else "procedure" if _LIST_ITEM.match(line)
                else "prose" if line.strip() else None)
        if want is None:                       # linea en blanco corta el bloque
            flush()
            continue
        if want != mode and buf:
            flush()
        mode = want
        buf.append(line)

    flush()
    return blocks
