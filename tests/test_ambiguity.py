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


# ── Los tres defectos que encontro la medicion de groundcheck (F2.3) ──────────
# Los tres hacian que el sistema NO respondiera preguntas que la documentacion
# si contesta: abstencion 0.73 en factual_lookup, 4 de 15.

JUNK = """| 04   | M9 BAYONET     | Repair |  | 0.2 |  |  | 1 |  |
| 0401 | LATCH ASSEMBLY | Repair |  | 0.2 |  |  | 1 |  |
| 05   | M9 SCABBARD    | Repair |  | 0.1 |  |  | 1 |  |"""


def test_comparador_en_la_pregunta_elige_la_fila_y_NO_pregunta():
    """El defecto mas caro: preguntaba por la columna de la RESPUESTA.

    "hasta 20" y "mas de 20" se reducian al mismo termino {20}, asi que la
    columna que separa las filas parecia fijada por la pregunta y el detector
    caia en Precalentamiento, ofreciendo ['ninguno', '95'] como opciones: las
    dos respuestas posibles, presentadas como si fueran la pregunta.
    """
    assert detect(
        "¿Qué precalentamiento requiere el A516 Gr.70 en espesores mayores a 20 mm?",
        [PREHEAT],
    ) is None


def test_valor_puntual_cae_en_un_solo_intervalo():
    """15 mm cae en 'hasta 20' y no en 'mas de 20'. No falta ningun dato."""
    assert detect("¿Hay que precalentar el A516 Gr.70 de 15 mm de espesor?", [PREHEAT]) is None
    assert detect("precalentamiento del A516 Gr.70 de 25 mm", [PREHEAT]) is None


def test_el_limite_es_inclusivo_y_eso_decide_la_fila():
    """20 justo: 'hasta 20' lo incluye, 'mas de 20' no. Un espesor de 20 mm
    tiene una sola respuesta, y tratar el limite como exclusivo la perderia."""
    assert detect("precalentamiento del A516 Gr.70 de 20 mm", [PREHEAT]) is None


def test_sin_espesor_SIGUE_siendo_ambiguo():
    """Contraprueba de los tres de arriba: sin el dato, se pregunta igual."""
    a = detect("precalentamiento para A516 Gr.70", [PREHEAT])
    assert a is not None
    assert set(a.options) == {"hasta 20", "mas de 20"}


def test_no_se_repregunta_con_una_opcion_vacia():
    """La lista de repuestos del TM se lee como tabla y producia
    "¿Para que (1) item no.?" con opciones ['', '1']. Nadie puede contestar
    eso: el sistema quedaba mudo sin salida. Mejor intentar responder — la
    respuesta pasa igual por groundedness y por el verificador."""
    assert detect("How long is the M9 bayonet blade?", [JUNK]) is None


def test_no_se_repregunta_por_una_columna_sin_nombre():
    """El encabezado era '04', el numero de la primera fila. Una columna que
    no tiene nombre no puede nombrar un criterio."""
    a = detect("How many major parts does the M9 scabbard consist of?", [JUNK])
    assert a is None


def test_un_comparador_dentro_de_otra_palabra_no_cuenta():
    """'over' vive dentro de 'covers' y 'under' dentro de 'understand'. Sin
    limites de palabra, una pregunta en ingles sin ningun numero salia con
    terminos {'>'}, el detector dejaba de cortar temprano y terminaba pidiendo
    elegir entre dos siglas de la tabla de abreviaturas del TM — para una
    pregunta que el manual contesta."""
    from shopfloor.ambiguity import _terms

    assert _terms("Which specification covers LUBRICATING OIL (LAW)?") == set()
    assert _terms("I do not understand the M9") == {"m9"}
    # y los comparadores de verdad siguen contando
    assert ">" in _terms("thickness over 20 mm")
    assert ">" in _terms("espesores mayores a 20 mm")
    assert "<" in _terms("hasta 20 mm")
