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
    ("El desempleo de agosto se situó en el 6,4% en la eurozona y el 6,1% en la Unión Europea.", []),
    ("El desempleo de agosto se situó en el 6,4% en la eurozona.", [("paro", "EA", 6.4, None)]),
    # Caso real (El Mundo, 18/10/2026): poblacion de Canada atribuida a Espana por la v2.
    ("Canadá es el segundo más extenso del planeta, con solo unos 40 millones de habitantes.", []),
    ("En Japón la tasa de paro se sitúa en el 2,5 %.", []),
    ("La tasa de paro se sitúa en el 10 % mientras Turquía sufre.", []),
    ("Tiene 49,3 millones de habitantes.", []),
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


def test_cited_periods():
    from truthnews.analysis.claims import period_of

    # Caso real (OKDIARIO, 18/10/2026): cita el dato de agosto; debe compararse con agosto, no con septiembre.
    got = extract(
        "No sería correcto utilizar ahora el IPC del 4,3% de agosto para la pensión.", "es", "ES", 2026, 10
    )
    assert [(c.indicator, c.value, c.period) for c in got] == [("inflacion", 4.3, "2026-08")]
    got = extract("La inflación de agosto se situó en el 4,3 %.", "es", "ES", 2026, 10)
    assert [(c.value, c.period) for c in got] == [(4.3, "2026-08")]
    assert period_of("la inflacion de diciembre", 2026, 10) == "2025-12"
    assert period_of("en el segundo trimestre", 2026, 10) == "2026-Q2"
    assert period_of("en septiembre de 2025", 2026, 10) == "2025-09"
    assert period_of("en mayo", 2026, 10) == "2026-05"
    assert period_of("un mayo cualquiera", 2026, 10) is None
    assert period_of("el paro es del 10 %", 2026, 10) is None


def test_helpers():
    assert indicator_name("paro") == "Tasa de paro" and indicator_name("x") == "x"
    assert sentences(
        "Corta. " + "Una frase suficientemente larga para contar. Otra más larga todavía aquí."
    ) == ["Una frase suficientemente larga para contar.", "Otra más larga todavía aquí."]
