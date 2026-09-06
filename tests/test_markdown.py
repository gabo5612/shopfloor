"""Contrato del parser de Markdown."""

import textwrap

from shopfloor.parse.markdown import parse_markdown

DOC = textwrap.dedent("""\
    # Guia de instalacion

    Texto introductorio de la guia.

    ## Requisitos

    | Componente | Version |
    |------------|---------|
    | PHP        | 8.1     |
    | WordPress  | 6.4     |

    ## Pasos

    1. Descargar el plugin.
    2. Subirlo a wp-content.
    3. Activarlo.

    ```php
    // esto no es una tabla ni una lista
    | fake | table |
    ```
    """)


def _write(tmp_path, text=DOC):
    p = tmp_path / "d.md"
    p.write_text(text, encoding="utf-8")
    return parse_markdown(p)


def test_todos_los_bloques_tienen_pagina(tmp_path):
    assert all(b.page_no >= 1 for b in _write(tmp_path))


def test_las_secciones_avanzan_de_pagina(tmp_path):
    b = _write(tmp_path)
    assert len({x.page_no for x in b}) >= 3


def test_la_tabla_se_detecta_entera(tmp_path):
    t = [b for b in _write(tmp_path) if b.kind == "table"]
    assert len(t) == 1
    assert "PHP" in t[0].content and "WordPress" in t[0].content


def test_la_lista_es_procedimiento(tmp_path):
    p = [b for b in _write(tmp_path) if b.kind == "procedure"]
    assert p and "Descargar" in p[0].content


def test_el_bloque_de_codigo_no_se_toma_por_tabla(tmp_path):
    for b in _write(tmp_path):
        if "fake" in b.content:
            assert b.kind == "prose"


def test_section_path_se_propaga(tmp_path):
    b = _write(tmp_path)
    assert any(x.section_path == "Requisitos" for x in b)


def test_documento_vacio_no_rompe(tmp_path):
    assert _write(tmp_path, "") == []
