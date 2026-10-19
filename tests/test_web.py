from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from truthnews.config import Settings
from truthnews.models import (
    Article,
    ArticleRevision,
    Claim,
    CrawlRun,
    Evidence,
    Outlet,
    Piece,
    Story,
    Thread,
    Topic,
    Verification,
)
from truthnews.web import seo
from truthnews.web.app import _ago, _dato, create_app
from truthnews.web.citations import cited_figures, word_diff


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
    assert "35 noticias" in home and "Contrastes de hoy" in home and "Verificado" in home
    assert 'href="/noticia/' not in home  # sin titulares sueltos en portada (peticion 2026-10-19)


def test_article_and_related(client, session):
    a = session.query(Article).filter_by(url="https://m.es/1").one()
    r = client.get(f"/noticia/{a.id}")
    assert r.status_code == 200
    assert "Leer en el medio original" in r.text and 'href="https://m.es/1"' in r.text
    assert "Solo lo publica Medio Uno: sin contraste todavía" in r.text
    assert "Titular 3" not in r.text  # sin titulares sueltos


def test_article_of_a_multi_outlet_story_redirects_to_the_comparison(client, session):
    now = datetime.now(UTC)
    st = Story(
        title="Contada por dos", category="politica", country="ES", first_seen=now, last_seen=now, n_outlets=2
    )
    session.add(st)
    session.flush()
    a = session.query(Article).filter_by(url="https://m.es/4").one()
    a.story_id = st.id
    session.commit()
    r = client.get(seo.path("noticia", a.id, a.title), follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == seo.path("historia", st.id, st.title) + "?medio=medio#m-medio"
    assert client.get(f"/noticia/{a.id}?ficha=1").status_code == 200


def test_article_cites_figures_tracks_changes_and_outlet_profile(client, session):
    """Peticion 2026-10-19: datos citados por fragmentos, prueba de captura y cambios del medio (ADR 0015)."""
    a = session.query(Article).filter_by(url="https://m.es/2").one()
    a.title = "La policía detiene a 22 personas en Irún"
    a.content_text = (
        "Los agentes detuvieron a 22 personas tras los disturbios. "
        + "Texto largo sin cifras que no se cita. " * 30
        + "Más de 300 manifestantes se concentraron en la plaza."
    )
    a.content_hash = "a" * 64
    a.word_count = 230
    session.add(
        ArticleRevision(
            article_id=a.id,
            outlet_id=a.outlet_id,
            field="title",
            before="La policía detiene a 2 personas en Irún",
            after=a.title,
            before_hash="b" * 64,
            after_hash="c" * 64,
        )
    )
    session.commit()
    page = client.get(f"/noticia/{a.id}").text
    assert "Datos citados" in page and "«Más de 300 manifestantes se concentraron en la plaza.»" in page
    assert "Texto largo sin cifras" not in page  # se cita por fragmentos, no el texto completo
    assert "Cambios detectados" in page and "<del>2</del>" in page and "<ins>22</ins>" in page
    assert (
        "Ficha de captura" in page and "https://web.archive.org/web/" in page and "aaaaaaaaaaaaaaaa" in page
    )
    outlet = client.get("/medio/medio").text
    assert "Noticias rastreadas" in outlet and "en 1 noticias" in outlet
    assert f'href="{seo.path("noticia", a.id, a.title)}#cambios"' in outlet
    # Un medio sin cambios lo dice en vez de mostrar una lista vacia.
    session.query(ArticleRevision).delete()
    session.commit()
    assert "Aún no hemos detectado cambios" in client.get("/medio/medio").text


def test_dato_formats_official_figures():
    assert _dato(10.0, "pct") == "10,0 %" and _dato(1234.5, "abs") == "1.234,5"
    assert _dato(2400.0) == "2.400" and _dato(None) == "—"


def test_citation_helpers():
    assert word_diff("detiene a 2 personas", "detiene a 22 personas") == [
        ("=", "detiene a"),
        ("-", "2"),
        ("+", "22"),
        ("=", "personas"),
    ]
    art = Article(title="Sin cifras", summary="Hubo 40 heridos. Hubo 40 heridos.", content_text=None)
    cites = cited_figures(art)
    assert [c["quote"] for c in cites] == ["Hubo 40 heridos."]  # sin repetir la misma frase
    assert cites[0]["figures"][0][:2] == ("heridos", 40.0)


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
        'class="meter bar"',
        'class="bars"',
        "Portada</a> › ",
        "En claro",
        "La verdad según los datos",
        "<b>10,0 %</b>",
        "Otro Medio (12,0 %, falso)",
        "Detenidos: los medios dan de 2.000 a 2.400.",
    ]:
        assert needle in page, needle
    # Cada cifra en disputa despliega que medios la dan, con enlace a su noticia.
    who = " ".join(part.split("</p>", 1)[0] for part in page.split('class="who-list"')[1:])
    assert f'href="{seo.path("noticia", a2.id, a2.title)}">Otro Medio</a>' in who and ">Medio Uno</a>" in who
    assert "<details><summary" in page and "ver qué medios" in page
    assert client.get("/historia/99999").status_code == 404
    assert "Historia comparada" in client.get("/contrastes?seccion=politica").text
    assert client.get("/contrastes?page=2").status_code == 200
    assert "Verdadero" in client.get("/metodologia").text
    assert "Falso 1" in client.get("/medio/otro").text
    assert "2 medios" in client.get(f"/noticia/{a2.id}").text
    # Contraste primero: la noticia de una historia comparada lleva a la historia con su medio destacado.
    r = client.get(seo.path("noticia", a2.id, a2.title), follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"] == seo.path("historia", st.id, st.title) + "?medio=otro#m-otro"
    target = client.get(r.headers["location"]).text
    first_card = target.split('class="ocard', 1)[1][:60]
    assert first_card.startswith(' target" id="m-otro"')
    # La evidencia muestra el dato oficial, no solo el enlace.
    assert "Dato oficial</span> <b>10,0 %</b>" in target and "frente a 12,0 %" in target
    ficha = client.get(seo.path("noticia", a2.id, a2.title) + "?ficha=1").text
    assert "Esta noticia se compara en 2 medios" in ficha and "Lo que comprobamos" in ficha
    assert "Ficha de captura" in ficha and f'href="{seo.path("noticia", a2.id, a2.title)}?ficha=1"' in target


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
    assert manifest["icons"][2]["purpose"] == "maskable"
    assert 'href="/static/favicon.svg" type="image/svg+xml"' in home
    for path in (
        "/static/logo.svg",
        "/static/mark.svg",
        "/static/favicon.svg",
        "/static/og-default.png",
        "/static/icon-180.png",
        "/static/icon-maskable-512.png",
        "/static/avatar-400.png",
        "/static/banner-1500x500.png",
    ):
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
    assert (
        f"<loc>http://localhost:8000{seo.path('historia', st.id, st.title)}</loc>" in sm.text
        and "/medio/medio</loc>" in sm.text
    )
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


def test_breaking_band_and_now_json(client, session):
    """Ultimo minuto: lo nuevo arriba, con impulso, cifras en disputa y el porque (peticion 2026-10-19)."""
    o2 = Outlet(
        slug="otro", name="Otro", homepage="https://o.es", country="ES", language="es", scope="national"
    )
    session.add(o2)
    session.flush()
    now = datetime.now(UTC)
    fresh = Story(
        title="Apagon en tres comunidades",
        category="sociedad",
        country="ES",
        first_seen=now - timedelta(minutes=20),
        last_seen=now - timedelta(minutes=5),
        n_articles=2,
        n_outlets=2,
        contrast={"disputas": ["afectados"]},
    )
    old = Story(
        title="Historia de anteayer",
        category="politica",
        country="ES",
        first_seen=now - timedelta(days=2),
        last_seen=now - timedelta(minutes=5),
        n_articles=2,
        n_outlets=2,
    )
    session.add_all([fresh, old])
    session.flush()
    session.query(Article).filter_by(url="https://m.es/2").one().story_id = fresh.id
    session.add(
        Article(
            outlet_id=o2.id,
            url="https://o.es/apagon",
            url_hash="a" * 64,
            title="Apagon",
            published_at=now,
            fetched_at=now,
            language="es",
            country="ES",
            category="sociedad",
            topics=[],
            story_id=fresh.id,
        )
    )
    session.add(
        Thread(title="Por que falla la red", status="publicado", anchor_story_id=fresh.id, content={})
    )
    session.commit()

    home = client.get("/").text
    band = home.split('class="breaking"')[1].split("</section>")[0]
    assert "Último minuto" in band and "Apagon en tres comunidades" in band
    assert "Historia de anteayer" not in band  # solo lo nacido en las ultimas horas
    assert "+2 en la última hora" in band  # m.es/2 tambien se rastreo ahora (fetched_at por defecto)
    assert "Cifras en disputa" in band
    assert "El porqué" in band and "/hilo/" in band
    assert "se revisan cada 10 min" in band and 'src="/static/live.js"' in home
    data = client.get("/ahora.json").json()
    assert data["latest"] > 0 and data["last_crawl"] > 0
    assert client.get("/static/live.js").status_code == 200
    en = client.get("/?lang=en").text
    assert "Latest" in en and "ago" in en


def test_no_breaking_band_without_fresh_stories(client):
    assert 'class="breaking"' not in client.get("/").text
    assert client.get("/ahora.json").json()["latest"] == 0
