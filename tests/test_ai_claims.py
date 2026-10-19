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
            "regional",
        ),
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
    assert "Francia" in ai.users[0] and "pais_del_medio" in ai.users[0]
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
