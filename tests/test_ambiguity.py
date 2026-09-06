"""Contrato del detector determinista de ambiguedad."""

from shopfloor.ambiguity import detect, parse_markdown_tables

TORQUE = """| Perno       |   Grado | Torque (N.m)   | Secuencia          |
|-------------|---------|----------------|--------------------|
| M24 cabezal |     8.8 | 680 +/- 30     | cruzada, 3 pasadas |
| M24 cabezal |    10.9 | 950 +/- 40     | cruzada, 3 pasadas |
| M16 tapa    |     8.8 | 190 +/- 10     | cruzada, 2 pasadas |"""

PREHEAT = """| Material   | Espesor (mm)   | Precalentamiento (C)   |
|------------|----------------|------------------------|
| A516 Gr.70 | hasta 20       | ninguno                |
| A516 Gr.70 | mas de 20      | 95                     |
| A106 Gr.B  | cualquiera     | 80                     |"""


def test_parsea_tabla_markdown():
    t = parse_markdown_tables(TORQUE)[0]
    assert t.header[0] == "Perno" and len(t.rows) == 3


def test_M24_sin_grado_es_AMBIGUO():
    """El caso que importa: 680 vs 950 segun el grado."""
    a = detect("¿cuál es el torque del perno M24 del cabezal?", [TORQUE])
    assert a is not None
    assert set(a.options) == {"8.8", "10.9"}
    assert "grado" in a.question.lower()


def test_M24_CON_grado_NO_es_ambiguo():
    assert detect("torque del perno M24 grado 8.8", [TORQUE]) is None


def test_M16_no_es_ambiguo_hay_una_sola_fila():
    assert detect("torque del perno M16 de la tapa", [TORQUE]) is None


def test_A516_sin_espesor_es_ambiguo():
    a = detect("precalentamiento para A516 Gr.70", [PREHEAT])
    assert a is not None
    assert set(a.options) == {"hasta 20", "mas de 20"}


def test_A106_no_es_ambiguo():
    assert detect("precalentamiento para A106 Gr.B", [PREHEAT]) is None


def test_pregunta_sin_terminos_no_dispara():
    assert detect("como se aprietan los pernos", [TORQUE]) is None


def test_sin_tablas_no_dispara():
    assert detect("torque del M24", ["texto sin ninguna tabla"]) is None
