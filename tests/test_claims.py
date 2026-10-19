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
    # Paro EPA por comunidad: solo con el nombre inequivoco de la comunidad y sin otro territorio.
    ("El paro en Andalucía se sitúa en el 16 % este trimestre.", [("paro", "ES-AN", 16.0, None)]),
    ("El paro en Madrid se sitúa en el 9 % este trimestre.", []),
    ("La inflación en Andalucía se sitúa en el 3 % este mes.", []),
    ("El paro en Galicia es del 8 % y en Cataluña del 9 %.", []),
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
    # Catalogo ampliado (2026-10-19): "% del PIB" es la unidad de deuda y deficit, no otro dato.
    ("La deuda pública es del 101,8 % del PIB.", [("deuda_publica", "ES", 101.8, None)]),
    ("El déficit público se situó en el 2,8 % del PIB.", [("deficit_publico", "ES", 2.8, None)]),
    ("La tasa de riesgo de pobreza es del 19,5 % en el país.", [("riesgo_pobreza", "ES", 19.5, None)]),
    (
        "La tasa de riesgo de pobreza o exclusión social es del 25,7 % en el país.",
        [("pobreza_exclusion", "ES", 25.7, None)],
    ),
    ("La tasa de riesgo de pobreza infantil es del 28,9 % en el país.", []),
    ("La inflación es del 2 % del PIB en ese cálculo.", []),
    # Una variacion no es el nivel (v4): "el paro baja un 2 %" no dice que la tasa de paro sea del 2 %.
    ("El paro baja un 2 % en septiembre en el país.", []),
    ("La inflación sube un 0,3 % en el mes en el país.", []),
    ("La deuda pública crece un 4 % en el año en el país.", []),
    ("El precio de la vivienda sube un 12,1 % en el país.", [("precio_vivienda", "ES", 12.1, None)]),
    # Otra medida del precio no es el indice oficial: no se juzga (seria injusto con el medio).
    ("El precio de la vivienda sube un 12,1 % según Idealista en el país.", []),
    ("El precio de la vivienda usada sube un 9 % en el país.", []),
    ("El precio de la vivienda sube un 8 % en el metro cuadrado de oferta.", []),
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


def test_core_inflation_is_its_own_series():
    got = [
        (c.indicator, c.value)
        for c in extract("La inflación subyacente se sitúa en el 2,4 % en el país.", "es", "ES", 2026)
    ]
    assert got == [("inflacion_subyacente", 2.4)]
    assert extract("La inflación de los alimentos se sitúa en el 6 % en el país.", "es", "ES", 2026) == []


def test_annual_gdp_growth_uses_the_cited_year():
    got = [
        (c.indicator, c.value, c.period)
        for c in extract("El PIB creció un 3,7 % en 2024 en España.", "es", "ES", 2026)
    ]
    assert got == [("pib_anual", 3.7, "2024")]
    assert extract("La economía crecerá un 2,2 % este año.", "es", "ES", 2026) == []
    assert extract("El PIB de 2019 creció un 2 % y el de 2024 un 3,7 %.", "es", "ES", 2026) == []
    assert [
        c.indicator for c in extract("El PIB crece un 0,7 % en el segundo trimestre.", "es", "ES", 2026)
    ] == ["pib_trimestral"]


def test_public_spending_and_revenue_over_gdp():
    got = [
        (c.indicator, c.value)
        for c in extract("El gasto público se situó en el 45,3 % del PIB en el país.", "es", "ES", 2026)
    ]
    assert got == [("gasto_publico", 45.3)]
    got = [
        (c.indicator, c.value)
        for c in extract("Los ingresos públicos alcanzan el 42,9 % del PIB en el país.", "es", "ES", 2026)
    ]
    assert got == [("ingresos_publicos", 42.9)]
    assert extract("El gasto público en sanidad es del 6,5 % del PIB en el país.", "es", "ES", 2026) == []
    assert extract("El gasto público es del 20 % del presupuesto en el país.", "es", "ES", 2026) == []
