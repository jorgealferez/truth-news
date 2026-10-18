from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from truthnews.config import Settings
from truthnews.models import Article, CrawlRun, Outlet
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
    assert "Titular 0" in home and "35 noticias" in home


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


def test_empty_home(engine):
    c = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    assert "Todavía no hay noticias" in c.get("/").text


def test_ago():
    now = datetime.now(UTC)
    assert _ago(None) == ""
    assert _ago(now - timedelta(minutes=5)) == "5 min"
    assert _ago((now - timedelta(hours=3)).replace(tzinfo=None)) == "3 h"
    assert _ago(datetime(2020, 1, 2, tzinfo=UTC)) == "02/01/2020"
