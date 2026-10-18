import pytest

from truthnews.analysis.claims import extract, indicator_name, sentences

CASES = [
    ("La tasa de paro se sitúa en el 12,5 % según el Gobierno.", [("paro", "ES", 12.5, None)]),
    ("Los combustibles empujan la inflación al 4,9%", [("inflacion", "ES", 4.9, None)]),
    ("El PIB crece un 0,7% en el segundo trimestre.", [("pib_trimestral", "ES", 0.7, None)]),
    ("La deuda pública baja al 101,6 %.", [("deuda_publica", "ES", 101.6, "baja")]),
    ("La inflación sube hasta el 5 % este mes en el país.", [("inflacion", "ES", 5.0, "sube")]),
    ("España tiene 49,3 millones de habitantes.", [("poblacion", "ES", 49_300_000.0, None)]),
    ("En Francia la inflación es del 3,4 %.", [("inflacion", "FR", 3.4, None)]),
    ("el producto interior bruto (PIB) ruso avanzará este año un 0,9 %, pese a la subida.", []),
    ("sin apoyo de un Estado con crecimiento anémico y una deuda del 119% del PIB.", []),
    ("y el pasado año las cuentas recogían un crecimiento económico del 2,4%.", []),
    ("Según Cuerpo, el paquete amortigua el shock de la inflación en torno al 40% o al 50%.", []),
    ("Macron dice que la inflación es del 3 %.", []),
    ("El paro juvenil supera el 25 % en el país.", []),
    ("El paro en Andalucía se sitúa en el 16 % este trimestre.", []),
    ("En 2019 la tasa de paro era del 14 % en el país.", []),
    ("La tasa de paro baja 0,3 puntos hasta el 10 %.", []),
    ("El PIB crece un 0,7 % este año.", []),  # sin trimestre: no es la serie trimestral
]


@pytest.mark.parametrize("text,expected", CASES)
def test_extraction_is_strict(text, expected):
    got = [(c.indicator, c.geo, c.value, c.direction) for c in extract(text, "es", "ES", 2026)]
    assert got == expected


def test_international_outlet_needs_explicit_country_and_dedup():
    assert extract("Unemployment rate stands at 5 %.", "en", "XX", 2026) == []
    got = extract(
        "In Germany the unemployment rate stands at 3.5 %. In Germany the unemployment rate stands at 3.5 %.",
        "en",
        "XX",
        2026,
    )
    assert [(c.geo, c.value) for c in got] == [("DE", 3.5)]


def test_helpers():
    assert indicator_name("paro") == "Tasa de paro" and indicator_name("x") == "x"
    assert sentences(
        "Corta. " + "Una frase suficientemente larga para contar. Otra más larga todavía aquí."
    ) == ["Una frase suficientemente larga para contar.", "Otra más larga todavía aquí."]
