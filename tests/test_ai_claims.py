from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from tests.test_ai import FakeAI
from truthnews.ai import claims as ai_claims
from truthnews.ai.client import AIError
from truthnews.analysis import pipeline
from truthnews.analysis.claims import ClaimCandidate, check_proposal, extract
from truthnews.analysis.verify import Verifier
from truthnews.data import Observation
from truthnews.models import Article, Claim, Outlet, Verification

NOW = datetime.now(UTC)
Y = NOW.year


def check(sentence, indicator, geo, value, period=None, direction=None, text=None, year=Y, month=10):
    return check_proposal(
        sentence, text or sentence, indicator, geo, value, period, direction, "ES", year, month
    )


# --- Validacion determinista de las propuestas -------------------------------------------------------
def test_accepts_what_rules_miss():
    s = "Con un 10,5 % de paro, el Gobierno presume de empleo en su balance."
    assert extract(s, "es", "ES", Y) == []  # las reglas no lo ven (cifra antes del indicador)
    c = check(s, "paro", "ES", 10.5)
    assert isinstance(c, ClaimCandidate) and (c.geo, c.value, c.unit) == ("ES", 10.5, "pct")


@pytest.mark.parametrize(
    ("sentence", "indicator", "geo", "value", "period", "reason"),
    [
        ("El paro juvenil se sitúa en el 25,3 % este trimestre.", "paro", "ES", 25.3, None, "colectivo"),
        (
            "La tasa de paro en Andalucía es del 15,2 % según el sindicato.",
            "paro",
            "ES",
            15.2,
            None,
            "comunidad",
        ),
        ("La tasa de paro en Madrid es del 9,1 % según el sindicato.", "paro", "ES-MD", 9.1, None, "dudoso"),
        (
            "La inflación en Andalucía es del 3,1 % según el instituto.",
            "inflacion",
            "ES-AN",
            3.1,
            None,
            "regional",
        ),
        ("El paro en Galicia es del 8 % y en España del 10 % hoy.", "paro", "ES-GA", 8.0, None, "a la vez"),
        ("La tasa de paro baja 0,4 puntos hasta el 10,5 % en total.", "paro", "ES", 10.5, None, "puntos"),
        ("La inflación se situará en el 2,1 % el próximo año.", "inflacion", "ES", 2.1, None, "prevision"),
        ("La tasa de paro es del 10,5 % según la encuesta oficial.", "paro", "ES", 11.0, None, "cifra"),
        (
            "La tasa de paro es del 10,5 % según la encuesta oficial.",
            "inflacion",
            "ES",
            10.5,
            None,
            "indicador",
        ),
        (
            "La tasa de paro es del 10,5 % según la encuesta oficial.",
            "magia",
            "ES",
            10.5,
            None,
            "desconocido",
        ),
        ("La tasa de paro es del 10,5 % según la encuesta oficial.", "paro", "FR", 10.5, None, "nombrado"),
        ("La tasa de paro en Francia es del 7,5 % según el instituto.", "paro", "ES", 7.5, None, "nombrado"),
        ("La tasa de paro en Japón es del 2,5 % según el gobierno.", "paro", "ES", 2.5, None, "sin serie"),
        (
            "La tasa de paro se sitúa en el 10 % mientras Francia sufre una crisis.",
            "paro",
            "FR",
            10.0,
            None,
            "contraste",
        ),
        ("La tasa de paro de agosto fue del 10,5 % según el INE.", "paro", "ES", 10.5, f"{Y}-07", "periodo"),
        (
            "La tasa de paro fue del 10,5 % según el INE en su balance.",
            "paro",
            "ES",
            10.5,
            f"{Y - 3}",
            "escrito",
        ),
        ("En 2019 la tasa de paro fue del 14,1 % según el INE oficial.", "paro", "ES", 14.1, None, "pasado"),
        ("La tasa de paro fue del 10,5 % según el INE en su balance.", "paro", "ES", 10.5, "ayer", "formato"),
        (
            "España tiene 48,6 millones de habitantes según el censo.",
            "poblacion",
            "ZZ",
            48_600_000,
            None,
            "desconocido",
        ),
        (
            "Hay 48,6 millones de habitantes según el padrón municipal.",
            "poblacion",
            "ES",
            48_600_000,
            None,
            "nombrado",
        ),
        (
            "El PIB crece un 0,6 % según los datos de hoy del INE.",
            "pib_trimestral",
            "ES",
            0.6,
            None,
            "contexto",
        ),
    ],
)
def test_rejections(sentence, indicator, geo, value, period, reason):
    out = check(sentence, indicator, geo, value, period)
    assert isinstance(out, str) and reason in out, out


def test_sentence_must_be_in_the_article():
    out = check(
        "La tasa de paro es del 9,1 % en España ahora.", "paro", "ES", 9.1, text="Otra cosa distinta aqui."
    )
    assert "literalmente" in out


def test_several_territories_take_the_nearest_to_the_figure():
    s = "La inflación en Francia fue del 2,1 % y en Alemania del 2,4 % en septiembre."
    c = check(s, "inflacion", "DE", 2.4)
    assert isinstance(c, ClaimCandidate) and c.geo == "DE" and c.period == f"{Y}-09"
    assert "inequivocamente" in check(s, "inflacion", "FR", 2.4)


def test_periods_and_direction():
    s = "La inflación sube al 2,9 % en septiembre, según el dato adelantado del INE."
    c = check(s, "inflacion", "ES", 2.9, period="", direction="sube")
    assert c.period == f"{Y}-09" and c.direction == "sube"  # el periodo lo fijan las reglas
    c = check(s, "inflacion", "ES", 2.9, direction="baja")
    assert c.direction is None  # el sentido propuesto no esta en la frase
    past = f"En {Y - 2} la deuda pública fue del 101,8 % del PIB, según Eurostat."
    assert check(past, "deuda_publica", "ES", 101.8, period=f"{Y - 2}").period == f"{Y - 2}"
    assert "pasado" in check(past, "deuda_publica", "ES", 101.8)
    q = "El PIB creció un 0,6 % en el segundo trimestre, según el INE."
    assert check(q, "pib_trimestral", "ES", 0.6, direction="sube").direction is None  # no direccional


def test_absolute_figures():
    c = check("España tiene 48,6 millones de habitantes según el censo.", "poblacion", "ES", 48_600_000)
    assert isinstance(c, ClaimCandidate) and c.unit == "abs"
    c = check("España alcanza los 48.619.695 habitantes según el padrón.", "poblacion", "ES", 48_619_695)
    assert isinstance(c, ClaimCandidate)


def test_candidate_sentences_and_schema():
    text = "La tasa de paro es del 10,5 %. Hace sol en Madrid y 25 grados hoy. La inflación fue del 3 % ayer."
    assert ai_claims.candidate_sentences(text) == [
        "La tasa de paro es del 10,5 %.",
        "La inflación fue del 3 % ayer.",
    ]
    schema = ai_claims.claims_schema()
    item = schema["properties"]["afirmaciones"]["items"]
    assert schema["additionalProperties"] is False and item["additionalProperties"] is False
    assert set(item["required"]) == set(item["properties"])
    assert "ninguno" in item["properties"]["indicador"]["enum"]


# --- Paso del worker: propone, valida, juzga y guarda ------------------------------------------------
@pytest.fixture()
def article(session):
    o = Outlet(slug="m", name="Medio", homepage="https://m", country="ES", language="es", scope="national")
    session.add(o)
    session.flush()
    a = Article(
        outlet_id=o.id,
        url="https://m/1",
        url_hash="1" * 64,
        title="Balance económico del Gobierno",
        summary="Con un 10,5 % de paro, el Gobierno presume de empleo.",
        content_text=(
            "La inflación en Francia fue del 2,1 % y en Alemania del 2,4 % en septiembre. "
            "El paro juvenil se sitúa en el 25,3 % este trimestre."
        ),
        published_at=NOW - timedelta(hours=1),
        language="es",
        country="ES",
        category="economia",
        topics=[],
    )
    session.add(a)
    session.flush()
    return a


def verifier():
    def fetch(source, geo, label):
        hist = {f"{Y}-08": 10.4, f"{Y}-09": 2.4 if geo == "DE" else 10.6}
        return Observation(
            "eurostat", label, "https://ec.europa.eu/x", f"{Y}-09", hist[f"{Y}-09"], history=hist
        )

    return Verifier(fetch)


def prop(i, indicator, geo, value, periodo="", comprobable=True):
    return {
        "id": i,
        "comprobable": comprobable,
        "indicador": indicator,
        "territorio": geo,
        "periodo": periodo,
        "valor": value,
        "sentido": "ninguno",
        "motivo": "",
    }


def test_run_validates_judges_and_stores(session, article):
    reply = {
        "afirmaciones": [
            prop(0, "paro", "ES", 10.5),  # aceptada: las reglas no la ven
            prop(1, "inflacion", "DE", 2.4),  # aceptada: la mas cercana a la cifra
            prop(1, "inflacion", "FR", 2.4),  # rechazada: no es la de Francia
            prop(2, "paro", "ES", 25.3),  # rechazada: colectivo
            prop(3, "paro", "ES", 1.0),  # id inexistente: ignorada
            prop(0, "ninguno", "ninguno", 0, comprobable=False),
        ]
    }
    ai = FakeAI([reply])
    out = ai_claims.run(session, ai, NOW - timedelta(hours=2), verifier())
    assert out["frases_candidatas"] == 3 and out["llamadas"] == 1 and out["aceptadas"] == 2
    assert out["juzgadas"] == 2 and sum(out["rechazos"].values()) == 2
    claims = {c.indicator: c for c in session.scalars(select(Claim))}
    assert claims["paro"].extractor == "ia" and claims["paro"].verification.verdict == "verdadero"
    assert claims["inflacion"].geo == "DE" and claims["inflacion"].period == f"{Y}-09"
    assert claims["inflacion"].verification.verdict == "verdadero"
    assert "Francia" in ai.users[0] and "pais_por_defecto" in ai.users[0]
    # Segunda pasada: las frases ya guardadas no se vuelven a enviar.
    again = ai_claims.run(session, FakeAI([{"afirmaciones": []}]), NOW - timedelta(hours=2), verifier())
    assert again["frases_candidatas"] == 1


def test_run_survives_ai_errors(session, article):
    out = ai_claims.run(session, FakeAI([AIError("rechazo")]), NOW - timedelta(hours=2), verifier())
    assert out["errores"] == 1 and out["juzgadas"] == 0
    assert session.scalars(select(Claim)).first() is None


def test_reverify_ia_claims_without_calling_the_ai(session, article):
    ai_claims.run(
        session,
        FakeAI([{"afirmaciones": [prop(1, "inflacion", "DE", 2.4)]}]),
        NOW - timedelta(hours=2),
        verifier(),
    )
    ver = session.scalars(select(Verification)).one()
    ver.method = "nivel/v1"
    article.content_text = "Texto cambiado sin la frase original de la inflación de Alemania."
    session.flush()
    out = pipeline.reverify_outdated(session, verifier())
    assert out == {"verdadero->sin-datos": 1}  # la frase ya no esta en el articulo: se retira con nota
    assert "Corregido" in ver.explanation


def test_new_indicators_real_sentences():
    # Frase real del rastreo del 2026-10-19 que las reglas no ven (la cifra va antes del indicador).
    s = "Hay familias en dificultades: el 19,7% de la población española está en riesgo de pobreza."
    c = check(s, "riesgo_pobreza", "ES", 19.7)
    assert isinstance(c, ClaimCandidate) and c.indicator == "riesgo_pobreza"
    arope = "El 25,7 % de la población está en riesgo de pobreza o exclusión social en España."
    assert "parecido" in check(arope, "riesgo_pobreza", "ES", 25.7)
    assert isinstance(check(arope, "pobreza_exclusion", "ES", 25.7), ClaimCandidate)
    gdp = "En el segundo trimestre el sector aporta el 0,6 % del PIB según el informe."
    assert "cifra" in check(gdp, "pib_trimestral", "ES", 0.6)
    deficit = "El déficit público cerró en el 2,8 % del PIB, según Hacienda."
    assert isinstance(check(deficit, "deficit_publico", "ES", 2.8), ClaimCandidate)


def test_variations_are_not_levels():
    assert "variacion" in check(
        "El paro registrado baja un 2 % en septiembre, según el ministerio.", "paro", "ES", 2.0
    )
    assert "variacion" in check(
        "La inflación ha subido un 0,3 % este mes en el conjunto del país.", "inflacion", "ES", 0.3
    )
    assert isinstance(
        check("Con un 10,5 % de paro, el país sigue a la cabeza.", "paro", "ES", 10.5), ClaimCandidate
    )
    assert isinstance(
        check("El PIB crece un 0,6 % en el segundo trimestre, según el INE.", "pib_trimestral", "ES", 0.6),
        ClaimCandidate,
    )


def test_regional_unemployment():
    c = check("La tasa de paro en Andalucía se sitúa en el 14,6 % según la EPA.", "paro", "ES-AN", 14.6)
    assert isinstance(c, ClaimCandidate) and c.geo == "ES-AN"
    two = "El paro en Cataluña es del 8,1 % y en Extremadura del 15,9 % según la EPA."
    assert check(two, "paro", "ES-EX", 15.9).geo == "ES-EX"
    assert "inequivocamente" in check(two, "paro", "ES-CT", 15.9)
    assert isinstance(
        check("El paro en la Comunidad de Madrid es del 9 % hoy.", "paro", "ES-MD", 9.0), ClaimCandidate
    )


def test_private_house_price_measures_are_not_the_official_index():
    s = "El precio de la vivienda sube un 12,1 % en un año, según el portal Idealista."
    assert "parecido" in check(s, "precio_vivienda", "ES", 12.1)
    ok = "El precio de la vivienda sube un 12,1 % en el segundo trimestre, según el INE."
    assert isinstance(check(ok, "precio_vivienda", "ES", 12.1), ClaimCandidate)


def test_core_inflation_is_not_the_general_one():
    s = "La inflación subyacente se moderó hasta el 2,4 % en septiembre, según el INE."
    assert "parecido" in check(s, "inflacion", "ES", 2.4)
    assert check(s, "inflacion_subyacente", "ES", 2.4).period == f"{Y}-09"


def test_annual_gdp_from_the_ai():
    s = "La economía española creció un 2,6 % en 2025, según el INE."
    c = check(s, "pib_anual", "ES", 2.6)
    assert isinstance(c, ClaimCandidate) and c.period == "2025"
    assert "contexto" in check("La economía española creció un 2,6 %, según el INE.", "pib_anual", "ES", 2.6)


def test_public_entry_points_without_articles():
    from truthnews.analysis.judge import judge_candidate, judge_text

    text = (
        "La tasa de paro se sitúa en el 10,5 % según el partido. Con un 10,5 % de paro, el país sigue igual."
    )
    judged = judge_text(text, "es", "ES", NOW, verifier())
    assert [(c.indicator, r.verdict) for c, r in judged] == [("paro", "verdadero")]
    items = [
        ai_claims.Item(s, text, "ES", NOW, ref="declaracion-7") for s in ai_claims.candidate_sentences(text)
    ]
    reply = {"afirmaciones": [prop(1, "paro", "ES", 10.5), prop(0, "paro", "FR", 10.5)]}
    got, stats = ai_claims.propose(FakeAI([reply]), items)
    assert [(it.ref, c.geo) for it, c in got] == [("declaracion-7", "ES")]
    assert stats["llamadas"] == 1 and sum(stats["rechazos"].values()) == 1
    assert judge_candidate(got[0][1], verifier()).verdict == "verdadero"
    assert ai_claims.propose(FakeAI([AIError("x")]), items)[1]["errores"] == 1


def test_effect_of_an_indicator_is_not_its_level():
    # Caso real (El Debate, 19/10/2026), juzgado Falso por la v5: la inflacion no es del 3,1 %.
    s = "Los ingresos crecen un 7,8 %, pero la inflación le resta un 3,1 %, y los gastos suben un 8,9 %."
    assert "variacion" in check(s, "inflacion", "ES", 3.1)
    assert "variacion" in check("El turismo suma un 0,4 % al paro de la región este año.", "paro", "ES", 0.4)


def test_expectations_and_annual_figures_are_not_the_latest_data():
    # Caso real (La Informacion, 19/10/2026), juzgado Falso por la v6: es una prevision para el ano.
    s = "Eleva su expectativa de inflación al 3,7% en 2026."
    assert "prevision" in check(s, "inflacion", "ES", 3.7, year=2026)
    assert extract(s, "es", "ES", 2026, 10) == []
    assert "ano en curso" in check(
        "La inflación media de 2026 será del 3,7 %.", "inflacion", "ES", 3.7, year=2026
    )
    assert extract("La inflación se sitúa en el 3,7 % en 2026 en el país.", "es", "ES", 2026, 10) == []


def test_subgroups_are_not_the_general_rate():
    # Caso real (ABC, 19/10/2026), juzgado Falso por la v8: es la tasa de las personas con discapacidad.
    s = "La tasa AROPE alcanza el 38,7% en este colectivo, frente al 30,6% entre quienes no la tienen."
    assert "colectivo" in check(s, "pobreza_exclusion", "ES", 38.7)
    assert extract(s, "es", "ES", 2026) == []
