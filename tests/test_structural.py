"""Contrato del chunker estructural.

Escrito por el arquitecto ANTES de la implementacion. El obrero implementa
contra estos tests; no los modifica.

La regla central de shopfloor (§3, Problema 1): una tabla NUNCA se parte sin
repetir su encabezado en cada fragmento. Partirla en silencio hace que el
sistema responda 950 N.m donde el valor correcto es 680.
"""

import pytest

from shopfloor.chunk.structural import chunk_blocks
from shopfloor.parse.types import Chunk, PageBlock

HEADER = "| Perno       | Grado | Torque (N.m) |"
SEP = "|-------------|-------|--------------|"


def _table(n_rows: int) -> str:
    rows = [f"| M{20 + i} cabezal | 8.8   | {600 + i * 10} +/- 30   |" for i in range(n_rows)]
    return "\n".join([HEADER, SEP, *rows])


def test_tabla_que_cabe_no_se_parte():
    blocks = [PageBlock(page_no=147, kind="table", content=_table(3))]
    out = chunk_blocks(blocks, max_chars=10_000)
    assert len(out) == 1
    assert out[0].content == _table(3)
    assert out[0].page_from == 147 and out[0].page_to == 147


def test_tabla_grande_repite_encabezado_en_CADA_fragmento():
    """El test que da sentido al proyecto."""
    blocks = [PageBlock(page_no=147, kind="table", content=_table(60))]
    out = chunk_blocks(blocks, max_chars=400)

    assert len(out) > 1, "una tabla de 60 filas con max_chars=400 debe fragmentarse"
    for i, c in enumerate(out):
        lines = c.content.splitlines()
        assert lines[0] == HEADER, f"fragmento {i} no empieza con el encabezado"
        assert lines[1] == SEP, f"fragmento {i} no tiene el separador"
        assert len(lines) > 2, f"fragmento {i} no tiene filas de datos"
        assert c.kind == "table"
        assert c.table_header == HEADER


def test_ninguna_fila_se_pierde_ni_se_duplica():
    original = _table(60)
    data_rows = [ln for ln in original.splitlines()[2:]]
    out = chunk_blocks([PageBlock(page_no=147, kind="table", content=original)], max_chars=400)

    seen = []
    for c in out:
        seen.extend(c.content.splitlines()[2:])
    assert seen == data_rows, "las filas deben aparecer todas, en orden, sin duplicar"


def test_prosa_larga_se_parte_y_conserva_la_pagina():
    texto = ". ".join(f"Oracion numero {i} sobre el montaje del cabezal" for i in range(200))
    out = chunk_blocks([PageBlock(page_no=42, kind="prose", content=texto)], max_chars=300)
    assert len(out) > 1
    assert all(c.page_from == 42 and c.page_to == 42 for c in out)
    assert all(len(c.content) <= 300 for c in out)


def test_procedimiento_no_se_corta_a_mitad_de_un_paso():
    pasos = "\n".join(f"{i}. Paso {i}: verificar el par de apriete y registrar el valor." for i in range(1, 21))
    out = chunk_blocks([PageBlock(page_no=88, kind="procedure", content=pasos)], max_chars=200)
    assert len(out) > 1
    for c in out:
        for line in c.content.splitlines():
            if line.strip():
                assert line[0].isdigit(), f"fragmento arranca a mitad de paso: {line!r}"


def test_section_path_se_propaga():
    sp = "4.3.2 Montaje del cabezal > Tabla 4-7"
    out = chunk_blocks(
        [PageBlock(page_no=147, kind="table", content=_table(40), section_path=sp)],
        max_chars=400,
    )
    assert all(c.section_path == sp for c in out)


def test_bloques_vacios_se_descartan():
    out = chunk_blocks(
        [
            PageBlock(page_no=1, kind="prose", content="   \n  "),
            PageBlock(page_no=2, kind="prose", content="contenido real"),
        ],
        max_chars=1000,
    )
    assert len(out) == 1
    assert out[0].page_from == 2


def test_devuelve_objetos_Chunk():
    out = chunk_blocks([PageBlock(page_no=1, kind="prose", content="hola")], max_chars=100)
    assert all(isinstance(c, Chunk) for c in out)


def test_page_no_invalido_es_rechazado_por_el_tipo():
    with pytest.raises(ValueError):
        PageBlock(page_no=0, kind="prose", content="x")
