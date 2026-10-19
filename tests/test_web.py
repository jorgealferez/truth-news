from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from truthnews.config import Settings
from truthnews.models import Article, Claim, CrawlRun, Evidence, Outlet, Piece, Story, Topic, Verification
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
        "Cómo lo cuenta cada medio",
        "Origen",
        'class="meter"',
        'class="bars"',
        "Portada</a> › ",
    ]:
        assert needle in page, needle
    assert client.get("/historia/99999").status_code == 404
    assert "Historia comparada" in client.get("/contrastes?seccion=politica").text
    assert client.get("/contrastes?page=2").status_code == 200
    assert "Verdadero" in client.get("/metodologia").text
    assert "Falso 1" in client.get("/medio/otro").text
    assert "2 medios" in client.get(f"/noticia/{a2.id}").text


def test_analysis_topic_and_verifications_pages(client, session):
    now = datetime.now(UTC)
    tp = Topic(
        title="Protestas en Francia",
        category="internacional",
        country="ES",
        first_seen=now,
        last_seen=now,
        n_stories=1,
        n_outlets=1,
    )
    session.add(tp)
    session.flush()
    st = Story(
        title="Historia del tema",
        category="internacional",
        country="ES",
        first_seen=now,
        last_seen=now,
        n_articles=1,
        n_outlets=1,
        topic_id=tp.id,
    )
    session.add(st)
    synth = {
        "que_dice_cada_medio": [
            {"medio_slug": "medio", "sintesis": "Cuenta el balance", "enfoque": "Cifras"},
            {"medio_slug": "desconocido", "sintesis": "x", "enfoque": "y"},
        ],
        "coincidencias": ["Hubo detenidos"],
        "diferencias": [{"aspecto": "Cifra", "detalle": "2.000 frente a 2.400"}],
        "datos": [{"dato": "2.000 detenidos", "fuente": "Medio Uno"}],
        "valoracion": {
            "conclusion": "Cobertura coherente",
            "confianza": "media",
            "lo_que_no_sabemos": ["El total"],
        },
        "historias_citadas": [],
    }
    session.add_all(
        [
            Piece(
                topic_id=tp.id,
                kind="analisis",
                status="publicada",
                title="Análisis de Francia",
                dek="Entradilla A",
                body=[{"subtitulo": "Qué pasó", "parrafos": ["Párrafo de análisis"]}],
                synthesis=synth,
                grounding={},
                model="claude-opus-5-5",
                input_hash="h",
                usage={},
            ),
            Piece(
                topic_id=tp.id,
                kind="opinion",
                status="publicada",
                title="Contar bien",
                dek="Conclusión",
                body=[{"subtitulo": "", "parrafos": ["Párrafo de opinión"]}],
                synthesis={},
                grounding={},
                model="claude-opus-5-5",
                input_hash="h",
                usage={},
            ),
            Piece(
                topic_id=tp.id,
                kind="analisis",
                status="revision",
                title="Pieza no publicada",
                dek="x",
                body=[],
                synthesis={},
                grounding={"ok": False},
                model="m",
                input_hash="h2",
                usage={},
            ),
        ]
    )
    session.commit()
    home = client.get("/").text
    assert "Análisis de Francia" in home and "Pieza no publicada" not in home
    lst = client.get("/analisis").text
    assert "Análisis de Francia" in lst and "Contar bien" in lst
    assert "Contar bien" in client.get("/analisis?tipo=opinion").text
    assert "Análisis de Francia" not in client.get("/analisis?tipo=opinion").text
    assert client.get("/analisis?page=2").status_code == 200
    page = client.get(f"/tema/{tp.id}").text
    for needle in [
        "Qué dice cada medio",
        "Cuenta el balance",
        "desconocido",
        "Hubo detenidos",
        "2.000 frente a 2.400",
        "Cobertura coherente",
        "El total",
        "Párrafo de análisis",
        "Párrafo de opinión",
        "Historia del tema",
        "elaborada con IA",
    ]:
        assert needle in page, needle
    assert client.get("/tema/9999").status_code == 404
    empty_topic = Topic(title="Sin piezas", category="politica", country="ES", first_seen=now, last_seen=now)
    session.add(empty_topic)
    session.commit()
    assert "Sin piezas" in client.get(f"/tema/{empty_topic.id}").text
    assert "Verificaciones" in client.get("/verificaciones").text


def test_empty_home(engine):
    c = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    assert "Todavía no hay noticias" in c.get("/").text


def test_ago():
    now = datetime.now(UTC)
    assert _ago(None) == ""
    assert _ago(now - timedelta(minutes=5)) == "5 min"
    assert _ago((now - timedelta(hours=3)).replace(tzinfo=None)) == "3 h"
    assert _ago(datetime(2020, 1, 2, tzinfo=UTC)) == "02/01/2020"


def _contrast(fg: str, bg: str) -> float:
    def lum(hex_color: str) -> float:
        rgb = [int(hex_color[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
        return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]

    hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def test_brand_palette_is_readable():
    import re
    from pathlib import Path

    css = (Path(__file__).parents[1] / "truthnews/web/static/site.css").read_text()
    tokens = dict(re.findall(r"--(\w+):(#[0-9a-f]{6})", css))
    for text_token in ("ink", "muted", "accent"):  # colores de texto: WCAG AA (4.5:1) sobre papel
        assert _contrast(tokens[text_token], tokens["paper"]) >= 4.5, text_token


def test_brand_assets_and_social_meta(client):
    home = client.get("/").text
    assert '<img src="/static/logo.svg" alt="NosMienten"' in home
    assert 'property="og:image" content="http://localhost:8000/static/og-default.png"' in home
    assert 'name="twitter:card" content="summary_large_image"' in home
    assert "Sin bandos. Con datos." in home and "nosmienten.com" in home
    assert '<meta property="og:title" content="NosMienten — Comparamos' in home
    ico = client.get("/favicon.ico")
    assert ico.status_code == 200 and ico.headers["content-type"] == "image/x-icon"
    manifest = client.get("/site.webmanifest").json()
    assert manifest["name"] == "NosMienten" and manifest["icons"][1]["sizes"] == "512x512"
    for path in ("/static/logo.svg", "/static/mark.svg", "/static/og-default.png", "/static/icon-180.png"):
        assert client.get(path).status_code == 200, path
    en = client.get("/acerca?lang=en").text
    assert "No sides. Just data." in en and 'content="en_GB"' in en


def test_story_card_shows_what_differs_and_relaunch(client, session):
    now = datetime.now(UTC)
    st = Story(
        title="Historia con contraste",
        category="sucesos",
        country="ES",
        first_seen=now - timedelta(days=5),
        last_seen=now - timedelta(days=5),
        n_articles=2,
        n_outlets=2,
        contrast_score=4.5,
        priority=4.6,
        contrast={"disputas": ["detenidos"], "veredictos": {}, "omisiones": 1, "lenguaje_cargado": 2},
        relaunched_at=now,
    )
    session.add(st)
    session.commit()
    home = client.get("/").text
    assert "Historia con contraste" in home and "Vuelve con datos nuevos" in home
    assert "Cifras en disputa: detenidos" in home and "Omisiones en 1 medio<" in home
    assert "Lenguaje cargado en 2 medios" in home


def test_distribution_robots_sitemap_rss_and_share(client, session):
    now = datetime.now(UTC)
    st = Story(
        title="Disturbios con cifras distintas",
        category="sucesos",
        country="ES",
        first_seen=now,
        last_seen=now,
        n_articles=2,
        n_outlets=2,
        priority=3,
        contrast={"disputas": ["detenidos"]},
    )
    session.add(st)
    session.flush()
    o2 = Outlet(
        slug="otro", name="Otro Medio", homepage="https://o.es", country="ES", language="es", scope="national"
    )
    session.add(o2)
    session.flush()
    for i, (o, n) in enumerate(((session.query(Outlet).filter_by(slug="medio").one(), "tres"), (o2, "doce"))):
        session.add(
            Article(
                outlet_id=o.id,
                story_id=st.id,
                url=f"https://x/{i}",
                url_hash=f"s{i:063d}",
                title=f"Disturbios: {n} detenidos",
                summary="",
                published_at=now,
                language="es",
                country="ES",
                category="sucesos",
                topics=[],
            )
        )
    session.commit()
    robots = client.get("/robots.txt").text
    assert "Disallow: /admin" in robots and "Sitemap: http://localhost:8000/sitemap.xml" in robots
    sm = client.get("/sitemap.xml")
    assert sm.headers["content-type"].startswith("application/xml")
    assert f"<loc>http://localhost:8000/historia/{st.id}</loc>" in sm.text and "/medio/medio</loc>" in sm.text
    rss = client.get("/rss.xml")
    assert rss.headers["content-type"].startswith("application/rss+xml")
    assert "Disturbios con cifras distintas" in rss.text and "cifras en disputa: detenidos" in rss.text
    png = client.get(f"/og/historia/{st.id}.png")
    assert png.status_code == 200 and png.content[:8] == b"\x89PNG\r\n\x1a\n"
    assert client.get(f"/og/historia/{st.id}.png").content == png.content  # cache
    assert client.get("/og/historia/99999.png").status_code == 404
    page = client.get(f"/historia/{st.id}").text
    assert f'content="http://localhost:8000/og/historia/{st.id}.png"' in page
    assert "https://wa.me/?text=Disturbios%20con%20cifras%20distintas" in page
    assert "detenidos%3A%20de%203%20a%2012%20seg%C3%BAn%20el%20medio" in page and "Copiar enlace" in page


def test_social_image_handles_long_titles_and_verdicts():
    from truthnews.web.social import story_image

    png = story_image(
        "Palabra " * 60, "Economía · 9 medios", [("paro", 10.0, 12.5, 4)], {"falso": 1, "verdadero": 2}, "x"
    )
    assert png[:4] == b"\x89PNG"
