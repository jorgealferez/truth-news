from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from truthnews.config import Settings
from truthnews.models import Article, Claim, CrawlRun, Evidence, Outlet, Story, Verification
from truthnews.web.app import _ago, create_app


@pytest.fixture()
def client(engine, session):
    o = Outlet(
        slug="medio",
        name="Medio Uno",
        homepage="https://m.es",
        country="ES",
        language="es",
        scope="regional",
        region="ES-AN",
        owner="Grupo X",
    )
    session.add(o)
    session.flush()
    now = datetime.now(UTC)
    for i in range(35):
        session.add(
            Article(
                outlet_id=o.id,
                url=f"https://m.es/{i}",
                url_hash=f"h{i:062d}",
                title=f"Titular {i}",
                summary="Resumen",
                published_at=now - timedelta(minutes=i),
                language="es",
                country="ES",
                region="ES-AN",
                category="politica" if i % 2 else "economia",
                topics=["Tema"],
            )
        )
    session.add(CrawlRun(finished_at=now))
    session.commit()
    return TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))


def test_pages_render(client):
    for path in [
        "/",
        "/seccion/politica",
        "/pais/ES",
        "/pais/es",
        "/region/ES-AN",
        "/medios",
        "/medios?pais=ES",
        "/medio/medio",
        "/acerca",
        "/seccion/economia?page=2",
    ]:
        r = client.get(path)
        assert r.status_code == 200, path
    home = client.get("/").text
    assert "Titular 0" in home and "35 noticias" in home and "Contrastes de hoy" in home


def test_article_and_related(client, session):
    a = session.query(Article).filter_by(url="https://m.es/1").one()
    r = client.get(f"/noticia/{a.id}")
    assert r.status_code == 200
    assert "Leer en el medio original" in r.text and 'href="https://m.es/1"' in r.text
    assert "Titular 3" in r.text  # relacionada de la misma seccion


@pytest.mark.parametrize(
    "path", ["/seccion/nada", "/pais/ZZ", "/region/ES-ZZ", "/medio/nada", "/noticia/99999"]
)
def test_not_found(client, path):
    assert client.get(path).status_code == 404


def test_pagination_links(client):
    page1 = client.get("/seccion/economia").text
    assert "?page=2" not in page1  # 18 articulos < 30
    assert "?page=2" in client.get("/pais/ES").text


def test_language_switch(client):
    r = client.get("/?lang=en")
    assert "Outlets" in r.text and r.cookies.get("lang") == "en"
    r = client.get("/idioma/en", headers={"referer": "/medios"}, follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/medios"
    assert client.get("/?lang=xx").text.count("Medios") >= 1


def test_health_and_api(client):
    assert client.get("/healthz").json() == {"status": "ok"}
    data = client.get("/api/articles?category=politica&country=es&region=es-an").json()
    assert len(data) == 17 and data[0]["outlet"] == "medio"


def test_home_shows_default_country_only(client, session):
    o = Outlet(slug="pt", name="PT", homepage="https://p.pt", country="PT", language="pt", scope="national")
    session.add(o)
    session.flush()
    session.add(
        Article(
            outlet_id=o.id,
            url="https://p.pt/1",
            url_hash="p" * 64,
            title="Noticia portuguesa",
            published_at=datetime.now(UTC),
            language="pt",
            country="PT",
            category="politica",
            topics=[],
        )
    )
    session.commit()
    assert "Noticia portuguesa" not in client.get("/").text
    assert "Noticia portuguesa" in client.get("/pais/PT").text


def test_comparator_pages(client, session):
    o2 = Outlet(
        slug="otro", name="Otro Medio", homepage="https://o.es", country="ES", language="es", scope="national"
    )
    session.add(o2)
    session.flush()
    now = datetime.now(UTC)
    st = Story(
        title="Historia comparada",
        category="politica",
        country="ES",
        first_seen=now,
        last_seen=now,
        n_articles=2,
        n_outlets=2,
    )
    session.add(st)
    session.flush()
    a1 = session.query(Article).filter_by(url="https://m.es/1").one()
    a1.story_id = st.id
    a1.title = "Caos: 2.000 detenidos"
    a2 = Article(
        outlet_id=o2.id,
        url="https://o.es/1",
        url_hash="o" * 64,
        title="2.400 detenidos",
        published_at=now,
        language="es",
        country="ES",
        category="politica",
        topics=[],
        story_id=st.id,
    )
    session.add(a2)
    session.flush()
    c = Claim(
        article_id=a2.id,
        story_id=st.id,
        outlet_id=o2.id,
        text="La tasa de paro es del 12 %",
        indicator="paro",
        geo="ES",
        value=12.0,
        unit="pct",
    )
    session.add(c)
    session.flush()
    v = Verification(
        claim_id=c.id,
        verdict="falso",
        confidence=0.8,
        explanation="El dato oficial es 10,0 %.",
        method="nivel",
    )
    v.evidence.append(
        Evidence(
            source="eurostat",
            label="Tasa de paro",
            url="https://ec.europa.eu/x",
            period="2026-08",
            value=10.0,
            payload={},
        )
    )
    session.add(v)
    session.commit()

    home = client.get("/").text
    assert "Historia comparada" in home and "2 medios" in home and "Falso 1" in home
    page = client.get(f"/historia/{st.id}").text
    for needle in [
        "Quién lo cuenta y cómo",
        "Cifras distintas según el medio",
        "2.400",
        "caos",
        "El dato oficial es 10,0 %.",
        "https://ec.europa.eu/x",
    ]:
        assert needle in page, needle
    assert client.get("/historia/99999").status_code == 404
    assert "Historia comparada" in client.get("/contrastes?seccion=politica").text
    assert client.get("/contrastes?page=2").status_code == 200
    assert "Verdadero" in client.get("/metodologia").text
    assert "Falso 1" in client.get("/medio/otro").text
    assert "2 medios" in client.get(f"/noticia/{a2.id}").text


def test_empty_home(engine):
    c = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    assert "Todavía no hay noticias" in c.get("/").text


def test_ago():
    now = datetime.now(UTC)
    assert _ago(None) == ""
    assert _ago(now - timedelta(minutes=5)) == "5 min"
    assert _ago((now - timedelta(hours=3)).replace(tzinfo=None)) == "3 h"
    assert _ago(datetime(2020, 1, 2, tzinfo=UTC)) == "02/01/2020"
