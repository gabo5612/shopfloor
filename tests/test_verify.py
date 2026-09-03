"""Contrato del verificador determinista. Escrito por el arquitecto."""

from anvil.verify import extract_facts, verify

DOC = ["El perno M24 grado 8.8 requiere 680 +/- 30 N.m.",
       "Cracks up to 0.50 in. (1.27 cm) are acceptable. See H.R. 471."]


def test_respuesta_fiel_pasa():
    r = verify("El torque es 680 N.m con tolerancia 30.", DOC)
    assert r.passed, r.unsupported


def test_numero_inventado_se_rechaza():
    r = verify("El torque es 950 N.m.", DOC)
    assert not r.passed
    assert "950" in r.unsupported


def test_codigo_inventado_se_rechaza():
    r = verify("Segun la norma H.R. 999 el limite es 0.50 in.", DOC)
    assert not r.passed
    assert any("999" in u for u in r.unsupported)


def test_codigo_con_formato_distinto_se_acepta():
    """'H.R.471' y 'H.R. 471' son el mismo dato."""
    assert verify("Ver H.R.471.", DOC).passed


def test_decimales_se_verifican():
    assert verify("Grietas de hasta 0.50 in. (1.27 cm).", DOC).passed
    assert not verify("Grietas de hasta 0.75 in.", DOC).passed


def test_numero_de_pagina_no_se_verifica():
    """Citar 'página 7' no es afirmar un dato del documento."""
    assert verify("Ver página 7 del manual: 680 N.m.", DOC).passed


def test_respuesta_sin_numeros_pasa():
    assert verify("Se debe limpiar y lubricar la pieza.", DOC).passed


def test_cuenta_los_datos_verificados():
    assert verify("680 y 30.", DOC).checked == 2


def test_marcador_de_cita_no_es_un_dato_afirmado():
    """'[1]' senala la fuente; no es un numero que el documento deba contener."""
    r = verify("El torque es 680 N.m. [1]", DOC)
    assert r.passed, r.unsupported


def test_marcador_de_cita_no_encubre_un_numero_inventado():
    r = verify("El torque es 950 N.m. [1]", DOC)
    assert not r.passed and "950" in r.unsupported
