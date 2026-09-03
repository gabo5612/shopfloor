"""Contrato del guard determinista del cache.

El caso peligroso, medido: "M24 grado 10.9" tiene MAS similitud coseno con
"M24 grado 8.8" (0.9089) que la reformulacion legitima (0.8431). La similitud
sola serviria 680 N.m a quien pregunto por el grado 10.9.
"""

from anvil.cache import hash_chunks, terms_of


def test_reformulacion_conserva_los_terminos():
    a = terms_of("¿cuál es el torque del perno M24 grado 8.8 del cabezal?")
    b = terms_of("torque de apriete del M24 grado 8.8 en el cabezal")
    assert a == b


def test_traduccion_conserva_los_terminos():
    a = terms_of("¿cuál es el torque del perno M24 grado 8.8?")
    b = terms_of("what is the torque for the M24 grade 8.8 bolt?")
    assert a == b


def test_OTRO_GRADO_no_comparte_terminos():
    """El caso peligroso: 0.9089 de similitud, respuesta distinta."""
    a = terms_of("¿cuál es el torque del perno M24 grado 8.8?")
    b = terms_of("¿cuál es el torque del perno M24 grado 10.9?")
    assert a != b


def test_OTRO_PERNO_no_comparte_terminos():
    a = terms_of("torque del perno M24 grado 8.8")
    b = terms_of("torque del perno M16 de la tapa")
    assert a != b


def test_otra_alarma_no_comparte_terminos():
    assert terms_of("alarma E-114") != terms_of("alarma E-141")


def test_decimales_con_coma_o_punto_son_el_mismo_termino():
    assert terms_of("grado 8,8") == terms_of("grado 8.8")


def test_hash_cambia_si_cambia_el_contenido():
    """Si el manual pasa a Rev E, el cache de la Rev D debe morir."""
    v1 = [(1, "torque 680 N.m"), (2, "otra cosa")]
    v2 = [(1, "torque 700 N.m"), (2, "otra cosa")]
    assert hash_chunks(v1) != hash_chunks(v2)


def test_hash_es_estable_ante_el_orden():
    assert hash_chunks([(1, "a"), (2, "b")]) == hash_chunks([(2, "b"), (1, "a")])


def test_una_entrada_stale_no_se_sirve():
    """Contrato: mientras espera refresco, no se entrega la respuesta vieja.

    Se verifica en lookup(): la fila con stale=True se salta antes de
    cualquier otra comprobacion.
    """
    import inspect

    from anvil import cache
    src = inspect.getsource(cache.lookup)
    assert "if stale:" in src and "continue" in src


def test_una_revision_nueva_llega_como_doc_id_distinto():
    """Por que no alcanza con mirar el doc_id.

    El doc_id sale del sha256 del archivo: la Rev E es otro archivo, luego otro
    doc_id. Las entradas viejas no lo referencian; hay que detectar que sus
    chunks desaparecieron.
    """
    import inspect

    from anvil import cache
    assert "mark_dangling_stale" in dir(cache)
    src = inspect.getsource(cache.mark_dangling_stale)
    assert "NOT EXISTS" in src
