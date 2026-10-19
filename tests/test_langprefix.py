from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from truthnews.config import Settings
from truthnews.models import Article, Outlet, Story
from truthnews.web import seo
from truthnews.web.app import create_app
from truthnews.web.langprefix import localize, rewrite_html

SITE = "http://localhost:8000"


def test_localize():
    assert localize("/", "en") == "/en"
    assert localize("/tema/3-x", "en") == "/en/tema/3-x"
    assert localize("/en/tema/3", "en") == "/en/tema/3" and localize("/en", "en") == "/en"
    for shared in (
        "/static/site.css",
        "/og/historia/1.png",
        "/rss.xml",
        "/sitemap.xml",
        "/admin",
        "/idioma/es",
    ):
        assert localize(shared, "en") == shared
    assert localize("https://elpais.com/x", "en") == "https://elpais.com/x"
    assert localize("//cdn.x/y", "en") == "//cdn.x/y" and localize("#a", "en") == "#a"


def test_rewrite_html_keeps_language_alternates_and_shared_files():
    html = (
        '<a href="/medios">M</a><a href="https://elpais.com/n">E</a><img src="/static/a.png">'
        f'<link rel="canonical" href="{SITE}/tema/3"><meta property="og:url" content="{SITE}/tema/3">'
        f'<meta property="og:image" content="{SITE}/static/og.png"><meta name="description" content="/no">'
        f'<link rel="alternate" hreflang="es" href="{SITE}/tema/3">'
        '<a href="/idioma/es?to=/" hreflang="es">ES</a>'
    )
    out = rewrite_html(html, "en", SITE)
    assert '<a href="/en/medios">' in out and 'href="https://elpais.com/n"' in out
    assert f'href="{SITE}/en/tema/3"' in out and f'content="{SITE}/en/tema/3"' in out
    assert f'content="{SITE}/static/og.png"' in out and 'content="/no"' in out
    assert f'hreflang="es" href="{SITE}/tema/3"' in out and 'href="/idioma/es?to=/"' in out


@pytest.fixture(params=[("es", "en")], ids=["indexed"])
def client(request, engine, session):
    o = Outlet(slug="m", name="Medio", homepage="https://m.es", country="ES", language="es", scope="national")
    session.add(o)
    session.flush()
    now = datetime.now(UTC)
    st = Story(
        title="Disturbios en Francia",
        category="internacional",
        country="ES",
        first_seen=now,
        last_seen=now,
        n_articles=2,
        n_outlets=2,
    )
    session.add(st)
    session.flush()
    session.add(
        Article(
            outlet_id=o.id,
            url="https://m.es/1",
            url_hash="a" * 64,
            title="Disturbios en Francia",
            published_at=now,
            language="es",
            country="ES",
            category="internacional",
            topics=[],
            story_id=st.id,
        )
    )
    session.commit()
    settings = Settings(database_url="sqlite://", indexed_languages=request.param)
    return TestClient(create_app(settings, engine=engine)), st


@pytest.fixture()
def noindex_client(engine, session):
    """Configuracion por defecto: solo el espanol se ofrece a buscadores (decision del usuario 2026-10-19)."""
    return TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))


def test_english_pages_under_prefix(client):
    c, st = client
    home = c.get("/en")
    assert home.status_code == 200 and '<html lang="en">' in home.text
    assert 'href="/en/medios"' in home.text and 'href="/static/site.css"' in home.text
    assert f'<link rel="alternate" hreflang="es" href="{SITE}/">' in home.text
    assert f'<link rel="alternate" hreflang="en" href="{SITE}/en">' in home.text
    assert f'hreflang="x-default" href="{SITE}/"' in home.text
    es = c.get("/medios").text
    assert '<html lang="es">' in es and 'href="/en/medios"' in es  # enlace a la version inglesa
    assert f'hreflang="en" href="{SITE}/en/medios"' in es
    want = seo.path("historia", st.id, st.title)
    r = c.get(f"/en/historia/{st.id}", follow_redirects=False)
    assert r.status_code == 301 and r.headers["location"] == "/en" + want
    page = c.get("/en" + want).text
    assert f'<link rel="canonical" href="{SITE}/en{want}">' in page
    assert f'<meta property="og:url" content="{SITE}/en{want}">' in page
    assert c.get("/en/static/site.css").status_code == 404
    assert c.get("/en/no-existe").status_code == 404


def test_sitemaps_robots_and_language_switch(client):
    c, st = client
    robots = c.get("/robots.txt").text
    assert f"Sitemap: {SITE}/sitemap.xml" in robots and f"Sitemap: {SITE}/sitemap-en.xml" in robots
    want = seo.path("historia", st.id, st.title)
    es = c.get("/sitemap.xml").text
    assert f"<loc>{SITE}{want}</loc>" in es and f'hreflang="en" href="{SITE}/en{want}"' in es
    en = c.get("/sitemap-en.xml").text
    assert f"<loc>{SITE}/en{want}</loc>" in en and f'hreflang="es" href="{SITE}{want}"' in en
    assert f"<loc>{SITE}/en</loc>" in en and 'xmlns:xhtml="http://www.w3.org/1999/xhtml"' in en
    assert c.get("/sitemap-xx.xml").status_code == 404
    r = c.get("/idioma/es?to=/medios", follow_redirects=False)
    assert (
        r.status_code == 303 and r.headers["location"] == "/medios" and "lang=es" in r.headers["set-cookie"]
    )
    assert c.get("/idioma/es?to=//evil.com", follow_redirects=False).headers["location"] == "/"


def test_english_pages_use_marked_headline_translations(client, session):
    from truthnews.models import ArticleTranslation

    c, st = client
    art = session.query(Article).filter_by(story_id=st.id).one()
    session.add(ArticleTranslation(article_id=art.id, lang="en", title="Riots in France", model="m"))
    session.commit()
    home = c.get("/en/contrastes").text
    assert '<a href="/en' in home and 'lang="en">Riots in France</a>' in home
    assert "AI machine translation of the original" in home
    page = c.get("/en" + seo.path("historia", st.id, st.title)).text
    assert "<title>Riots in France — " in page
    assert "Riots in France" not in c.get("/contrastes").text  # en espanol, el titular original


def test_untranslated_languages_are_served_but_not_offered_to_search_engines(noindex_client):
    c = noindex_client
    en = c.get("/en/medios").text
    assert '<html lang="en">' in en and '<meta name="robots" content="noindex, follow">' in en
    assert 'hreflang="es" href=' not in en.split("<body")[0]  # sin alternos en la cabecera
    es = c.get("/medios").text
    assert "noindex" not in es and '<link rel="alternate" hreflang' not in es
    assert 'href="/en/medios"' in es  # el selector de idioma sigue llevando a la version inglesa
    robots = c.get("/robots.txt").text
    assert f"Sitemap: {SITE}/sitemap.xml" in robots and "sitemap-en" not in robots
    assert c.get("/sitemap-en.xml").status_code == 404
    sm = c.get("/sitemap.xml").text
    assert "/en" not in sm and "xhtml:link" not in sm
