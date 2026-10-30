from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from truthnews.ai.client import AIError, AIResult
from truthnews.config import Settings
from truthnews.data import Observation
from truthnews.investigate import (
    DEFAULT_QUESTIONS,
    countries_in,
    gdelt_query,
    process_pending,
    related_stories,
    seed_defaults,
)
from truthnews.models import Article, Investigation, Outlet, Story
from truthnews.web.admin import csrf_token, text_coverage
from truthnews.web.app import create_app


class FakeVerifier:
    def observation(self, indicator, geo):
        if geo == "XX" or indicator == "precio_vivienda":
            return None
        today = datetime.now(UTC)
        period = f"{today.year}-{today.month:02d}"
        return Observation(
            "Eurostat", f"{indicator} {geo}", "https://ec.europa.eu/x", period, 7.25, history={period: 7.25}
        )


def fake_timeline(query, span):
    assert span == "30d"
    return [{"date": "20261001", "value": 0.5}, {"date": "20261002", "value": 1.5}]


def _story(session, title, outlets=3, days_ago=1):
    now = datetime.now(UTC) - timedelta(days=days_ago)
    st = Story(
        title=title,
        category="internacional",
        country="ES",
        first_seen=now,
        last_seen=now,
        n_articles=outlets,
        n_outlets=outlets,
    )
    session.add(st)
    session.flush()
    for i in range(outlets):
        o = session.query(Outlet).filter_by(slug=f"m{i}").one_or_none()
        if o is None:
            o = Outlet(
                slug=f"m{i}",
                name=f"M{i}",
                homepage="https://m",
                country="ES",
                language="es",
                scope="national",
            )
            session.add(o)
            session.flush()
        session.add(
            Article(
                outlet_id=o.id,
                story_id=st.id,
                url=f"https://m/{st.id}/{i}",
                url_hash=f"{st.id:032d}{i:032d}",
                title=title,
                summary="",
                published_at=now,
                language="es",
                country="ES",
                category="internacional",
                topics=[],
            )
        )
    session.flush()
    return st


def test_countries_and_query():
    assert countries_in("disturbios en francia") == ["FR"]
    europe = countries_in("protestas en europa")
    assert "EU" in europe and "DE" in europe
    assert gdelt_query("¿Qué influencia tiene Estados Unidos sobre Rusia e Israel?") == (
        '"united states" russia israel'
    )
    assert gdelt_query("¿Algo sin terminos conocidos?") == ""
    # Accidentes ferroviarios (2026-10-29, choque AVE-Iryo en Toledo): antes la consulta salia vacia.
    assert gdelt_query("¿Que paso en el choque de trenes de Toledo?") == "collision train"


def test_related_stories_need_terms_and_several_outlets(session):
    hit = _story(session, "Disturbios en Francia tras la reforma")
    _story(session, "Disturbios en Francia contados por un solo medio", outlets=1)
    _story(session, "Disturbios en Francia del ano pasado", days_ago=60)
    _story(session, "Receta de tortilla")
    found = related_stories(session, "¿Por qué hay disturbios en Francia?", ["FR"])
    assert found == [hit]


def test_seed_is_idempotent(session):
    assert seed_defaults(session) == len(DEFAULT_QUESTIONS)
    assert seed_defaults(session) == 0


def test_process_without_ai_publishes_verifiable_report(session):
    _story(session, "Disturbios en Francia tras la reforma")
    session.add(Investigation(question="¿Por qué hay tantos disturbios en Francia?"))
    session.flush()
    out = process_pending(session, verifier=FakeVerifier(), timeline=fake_timeline)
    assert out == {"processed": 1, "failed": 0}
    inv = session.query(Investigation).one()
    assert inv.status == "publicada" and inv.error is None
    r = inv.report
    assert r["paises"] == ["FR"] and r["historias"][0]["medios"] == 3
    assert {d["indicador"] for d in r["datos"]} == {"paro FR", "inflacion FR"}
    assert r["cobertura_mundial"]["consulta"] == "riots france" and r["cobertura_mundial"]["media"] == 1.0
    assert "analisis" not in r


class FakeAI:
    def __init__(self, data=None, error=None):
        self.data, self.error = data, error

    def structured(self, system, user, schema):
        assert "INFORME" in user and schema["type"] == "object"
        if self.error:
            raise AIError(self.error)
        return AIResult(data=self.data, model="modelo-test")


@pytest.mark.parametrize(
    ("text", "key", "ok"),
    [
        ("El paro esta en 7.25 segun Eurostat", "analisis", True),
        ("El paro esta en 31.4", "analisis_en_revision", False),
    ],
)
def test_process_with_ai_checks_grounding(session, text, key, ok):
    session.add(Investigation(question="¿Que pasa con el paro en Alemania?"))
    session.flush()
    process_pending(session, verifier=FakeVerifier(), ai=FakeAI({"conclusion": text}), timeline=fake_timeline)
    r = session.query(Investigation).one().report
    assert key in r and r["fundamento"]["ok"] is ok and r["modelo"] == "modelo-test"


def test_ai_error_and_failures_are_recorded(session):
    session.add_all(
        [Investigation(question="¿Que pasa con el paro en Alemania?"), Investigation(question="¿Otra?")]
    )
    session.flush()

    def broken_timeline(query, span):
        raise RuntimeError("gdelt caido")

    out = process_pending(
        session, verifier=FakeVerifier(), ai=FakeAI(error="rechazo"), timeline=broken_timeline
    )
    # La primera tiene consulta GDELT (unemployment germany) y falla; la segunda no consulta GDELT.
    assert out == {"processed": 1, "failed": 1}
    first, second = session.query(Investigation).order_by(Investigation.id).all()
    assert first.status == "error" and "gdelt caido" in first.error
    assert second.status == "publicada" and second.report["analisis_error"] == "rechazo"


@pytest.fixture()
def admin_client(engine):
    return TestClient(create_app(Settings(database_url="sqlite://", admin_password="secreto"), engine=engine))


def test_admin_disabled_without_password(engine):
    client = TestClient(create_app(Settings(database_url="sqlite://", admin_password=""), engine=engine))
    assert client.get("/admin").status_code == 503


def test_admin_requires_credentials(admin_client):
    assert admin_client.get("/admin").status_code == 401
    assert admin_client.get("/admin", auth=("admin", "mala")).status_code == 401


def test_admin_balance_and_create_investigation(admin_client, session):
    _story(session, "Disturbios en Francia tras la reforma")
    session.commit()
    auth = ("admin", "secreto")
    r = admin_client.get("/admin", auth=auth)
    assert r.status_code == 200 and "Balance de la operación" in r.text and "historias multimedio" in r.text
    token = csrf_token(Settings(admin_password="secreto"))
    bad = admin_client.post("/admin/investigaciones", auth=auth, data={"question": "x" * 20, "csrf": "no"})
    assert bad.status_code == 403
    short = admin_client.post("/admin/investigaciones", auth=auth, data={"question": "corta", "csrf": token})
    assert short.status_code == 422
    ok = admin_client.post(
        "/admin/investigaciones",
        auth=auth,
        data={"question": "  ¿Por qué suben los alquileres en Portugal?  ", "csrf": token},
        follow_redirects=False,
    )
    assert ok.status_code == 303 and ok.headers["location"] == "/admin"
    session.expire_all()
    inv = session.query(Investigation).one()
    assert inv.question == "¿Por qué suben los alquileres en Portugal?" and inv.status == "pendiente"
    assert "suben los alquileres" in admin_client.get("/admin", auth=auth).text


def test_public_investigation_pages(admin_client, session):
    pending = Investigation(question="¿Pendiente de investigar?")
    done = Investigation(
        question="¿Por qué hay disturbios en Francia?",
        status="publicada",
        report={
            "pregunta": "¿Por qué hay disturbios en Francia?",
            "paises": ["FR"],
            "historias": [{"id": 1, "titular": "Disturbios en Francia", "medios": 3, "ultima": "17/10/2026"}],
            "datos": [],
            "cobertura_mundial": {
                "consulta": "riots france",
                "puntos": 0,
                "media": None,
                "ultimo": None,
                "maximo": None,
                "fuente": "GDELT",
            },
            "metodo": "metodo",
        },
    )
    session.add_all([pending, done])
    session.commit()
    listing = admin_client.get("/investigaciones")
    assert listing.status_code == 200 and "disturbios en Francia" in listing.text
    assert "Pendiente de investigar" not in listing.text
    page = admin_client.get(f"/investigacion/{done.id}")
    assert page.status_code == 200 and "Disturbios en Francia" in page.text
    from truthnews.web import structured

    (art,) = structured.of_type(page.text, "NewsArticle")
    assert art["headline"] == "¿Por qué hay disturbios en Francia?" and art["datePublished"]
    assert structured.of_type(page.text, "BreadcrumbList")[0]["itemListElement"][1]["name"]
    assert admin_client.get(f"/investigacion/{pending.id}").status_code == 404
    assert admin_client.get("/investigacion/9999").status_code == 404


def test_admin_text_coverage_by_section_last_24h(admin_client, session):
    _story(session, "Cumbre del clima en Belem", days_ago=0)
    _story(session, "Huelga de transportes de la semana pasada", days_ago=3)  # fuera de las 24 h
    recent = session.query(Article).filter(Article.title == "Cumbre del clima en Belem").all()
    for i, a in enumerate(recent):
        a.content_text = "Texto completo." if i == 0 else None
    session.commit()
    assert text_coverage(session) == [{"category": "internacional", "total": 3, "with_text": 1, "pct": 33.3}]
    page = admin_client.get("/admin", auth=("admin", "secreto")).text
    assert "Artículos con texto completo (últimas 24 h)" in page and "33.3" in page


def test_failed_refresh_keeps_the_published_analysis(session):
    """Produccion 2026-10-30: el foco reabre la investigacion cada 30 min; con el tope de IA agotado el
    informe nuevo, sin analisis, borraba el publicado (/investigacion/3 se quedo sin respuesta)."""
    inv = Investigation(question="¿Que pasa con el paro en Alemania?")
    session.add(inv)
    session.flush()
    process_pending(
        session,
        verifier=FakeVerifier(),
        ai=FakeAI({"conclusion": "Eurostat da 7.25"}),
        timeline=fake_timeline,
    )
    assert "analisis" in inv.report
    inv.status = "pendiente"
    process_pending(
        session, verifier=FakeVerifier(), ai=FakeAI(error="presupuesto agotado"), timeline=fake_timeline
    )
    assert inv.status == "publicada" and inv.report["analisis"] == {"conclusion": "Eurostat da 7.25"}
    assert inv.report["actualizacion_fallida"] == "presupuesto agotado"
