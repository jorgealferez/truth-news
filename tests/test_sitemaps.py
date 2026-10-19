import re
from datetime import UTC, datetime, timedelta
from xml.etree import ElementTree

import pytest
from fastapi.testclient import TestClient

from truthnews.config import Settings
from truthnews.models import Article, Claim, Outlet, Story, Verification
from truthnews.web import seo, sitemaps
from truthnews.web.app import create_app

SITE = "http://localhost:8000"
NOW = datetime(2026, 10, 19, 12, 0, tzinfo=UTC)


def _story(session, title, n_outlets=2, age=timedelta(0), outlet=None):
    when = datetime.now(UTC) - age
    st = Story(
        title=title,
        category="politica",
        country="ES",
        first_seen=when,
        last_seen=when,
        updated_at=when,
        n_articles=n_outlets,
        n_outlets=n_outlets,
    )
    session.add(st)
    session.flush()
    return st


@pytest.fixture()
def site(engine, session):
    o = Outlet(
        slug="medio", name="Medio", homepage="https://m.es", country="ES", language="es", scope="national"
    )
    session.add(o)
    session.flush()
    fresh = _story(session, "Disturbios en Paris con cifras distintas", n_outlets=6)
    old = _story(session, "Presupuestos del ano pasado", age=timedelta(days=40))
    _story(session, "Solo un medio", n_outlets=1)
    art = Article(
        outlet_id=o.id,
        url="https://m.es/1",
        url_hash="a" * 64,
        title="x",
        published_at=datetime.now(UTC),
        language="es",
        country="ES",
        category="politica",
        topics=[],
        story_id=fresh.id,
    )
    session.add(art)
    session.flush()
    for value, verdict in ((12.0, "falso"), (13.0, "sin-datos")):
        c = Claim(
            article_id=art.id,
            story_id=fresh.id,
            outlet_id=o.id,
            text=f"El paro es del 12 % ({verdict})",
            indicator="paro",
            geo="ES",
            value=value,
            unit="pct",
        )
        session.add(c)
        session.flush()
        session.add(
            Verification(claim_id=c.id, verdict=verdict, confidence=0.8, explanation="x", method="nivel")
        )
    session.commit()
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    return client, fresh, old


def test_robots_lists_index_and_news(site):
    c, _, _ = site
    robots = c.get("/robots.txt").text
    assert f"Sitemap: {SITE}/sitemap.xml" in robots and f"Sitemap: {SITE}/sitemaps/news.xml" in robots


def test_index_points_to_every_non_empty_file_with_lastmod(site):
    c, fresh, _ = site
    r = c.get("/sitemap.xml")
    assert r.status_code == 200 and r.headers["content-type"].startswith("application/xml")
    assert r.headers["x-robots-tag"] == "noindex" and "max-age=300" in r.headers["cache-control"]
    assert "last-modified" in r.headers
    root = ElementTree.fromstring(r.content)
    ns = {"s": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    locs = [e.text for e in root.findall("s:sitemap/s:loc", ns)]
    assert locs[0] == f"{SITE}/sitemaps/news.xml"
    for name in ("paginas-1", "historias-1", "verificaciones-1"):
        assert f"{SITE}/sitemaps/{name}.xml" in locs
    assert f"{SITE}/sitemaps/hilos-1.xml" not in locs  # sin hilos publicados: sin fichero vacio
    mods = [e.text for e in root.findall("s:sitemap/s:lastmod", ns)]
    assert all(re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\+00:00", m) for m in mods)


def test_story_file_has_dates_priority_frequency_and_image(site):
    c, fresh, old = site
    r = c.get("/sitemaps/historias-1.xml")
    assert r.status_code == 200 and "max-age=900" in r.headers["cache-control"]
    root = ElementTree.fromstring(r.content)
    ns = {
        "s": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "image": "http://www.google.com/schemas/sitemap-image/1.1",
    }
    urls = {u.find("s:loc", ns).text: u for u in root.findall("s:url", ns)}
    assert len(urls) == 2  # la historia de un solo medio no se ofrece
    f = urls[SITE + seo.path("historia", fresh.id, fresh.title)]
    assert f.find("s:changefreq", ns).text == "hourly" and float(f.find("s:priority", ns).text) >= 0.8
    assert f.find("image:image/image:loc", ns).text == f"{SITE}/og/historia/{fresh.id}.png"
    o = urls[SITE + seo.path("historia", old.id, old.title)]
    assert o.find("s:changefreq", ns).text == "monthly" and o.find("s:priority", ns).text == "0.5"
    assert o.find("s:lastmod", ns).text.endswith("+00:00")


def test_pages_and_verifications_files(site):
    c, _, _ = site
    pages = c.get("/sitemaps/paginas-1.xml").text
    assert f"<loc>{SITE}/</loc>" in pages and "<priority>1.0</priority>" in pages
    assert f"<loc>{SITE}/medio/medio</loc>" in pages and f"<loc>{SITE}/region/ES-MD</loc>" in pages
    checks = c.get("/sitemaps/verificaciones-1.xml").text
    assert checks.count("<url>") == 1  # la "sin datos" no se ofrece


def test_unknown_or_out_of_range_files_are_404(site):
    c, _, _ = site
    for path in ("historias-2", "historias-0", "nada-1", "historias-x", "hilos-1"):
        assert c.get(f"/sitemaps/{path}.xml").status_code == 404, path


def test_files_split_at_page_size(site, monkeypatch, session):
    c, _, _ = site
    monkeypatch.setattr(sitemaps, "PAGE_SIZE", 1)
    index = c.get("/sitemap.xml").text
    assert "/sitemaps/historias-1.xml" in index and "/sitemaps/historias-2.xml" in index
    assert "historias-3" not in index
    one, two = (c.get(f"/sitemaps/historias-{n}.xml").text for n in (1, 2))
    assert one.count("<url>") == 1 and two.count("<url>") == 1 and one != two
    assert c.get("/sitemaps/historias-3.xml").status_code == 404


def test_default_page_size_is_the_requested_maximum():
    assert sitemaps.PAGE_SIZE == 1000 and sitemaps.NEWS_MAX == 1000


def test_news_sitemap_has_only_last_48h_with_google_news_fields(site, session):
    c, fresh, old = site
    _story(session, "De hace tres dias", age=timedelta(days=3))
    session.commit()
    r = c.get("/sitemaps/news.xml")
    assert r.status_code == 200
    root = ElementTree.fromstring(r.content)
    ns = {
        "s": "http://www.sitemaps.org/schemas/sitemap/0.9",
        "news": "http://www.google.com/schemas/sitemap-news/0.9",
    }
    urls = root.findall("s:url", ns)
    assert [u.find("s:loc", ns).text for u in urls] == [SITE + seo.path("historia", fresh.id, fresh.title)]
    n = urls[0].find("news:news", ns)
    assert n.find("news:publication/news:name", ns).text == "NosMienten"
    assert n.find("news:publication/news:language", ns).text == "es"
    assert n.find("news:title", ns).text == fresh.title
    assert n.find("news:publication_date", ns).text.endswith("+00:00")


def test_priority_and_frequency_rules():
    assert sitemaps.story_priority(2, NOW, NOW) == 0.7
    assert sitemaps.story_priority(30, NOW, NOW) == 1.0
    assert sitemaps.story_priority(2, NOW - timedelta(days=5), NOW) == 0.6
    assert sitemaps.story_priority(1, None, NOW) == 0.5
    assert sitemaps.changefreq(NOW - timedelta(hours=3), NOW) == "hourly"
    assert sitemaps.changefreq(NOW - timedelta(days=3), NOW) == "daily"
    assert sitemaps.changefreq(NOW - timedelta(days=10), NOW) == "weekly"
    assert sitemaps.changefreq(None, NOW) == "monthly"
    naive = datetime(2026, 10, 19, 8, 5, 7, 123)
    assert sitemaps.w3c(naive) == "2026-10-19T08:05:07+00:00"


def test_xml_is_escaped():
    e = sitemaps.Entry("/historia/1-a?b=1&c=2")
    assert "&amp;c=2" in sitemaps.urlset_xml([e], SITE)
    n = sitemaps.NewsEntry("/historia/1", "Sanchez & <Feijoo>", NOW)
    ElementTree.fromstring(sitemaps.news_xml([n], SITE, "A&B", "es"))  # XML valido
