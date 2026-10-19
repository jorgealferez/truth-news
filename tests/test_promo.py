import asyncio
from dataclasses import replace
from datetime import timedelta

import httpx
import pytest
from sqlalchemy import func, select

from truthnews.analysis.pipeline import assign_stories
from truthnews.config import Settings
from truthnews.crawler.ingest import crawl, sync_registry
from truthnews.models import Article, Outlet, Story, utcnow
from truthnews.promo import is_promotional
from truthnews.registry import FeedSpec, OutletSpec


@pytest.mark.parametrize(
    "title,summary,url",
    [
        # Las tres piezas de la captura del usuario (nosmienten.com, 2026-10-19).
        (
            "El secador de Cecotec que perfuma el cabello mientras lo seca y controla el encrespamiento "
            "por menos de 40 euros",
            "",
            "https://medio.test/tecnologia/secador",
        ),
        ("Los mejores cepillos y pastas dentales para la higiene bucal de tu perro y gato", "", ""),
        ("Los mejores cepillos de dientes eléctricos baratos por menos de 30€", "", ""),
        ("Una freidora sin aceite muy vendida", "", "https://www.elmundo.es/escaparate/cocina/freidora.html"),
        ("Esta crema hidratante arrasa", "", "https://medio.test/compras/belleza/crema"),
        ("Las mejores ofertas del Black Friday en televisores", "", ""),
        ("Chollos del día: auriculares inalámbricos", "", ""),
        ("Este robot aspirador tiene un descuento brutal en Amazon", "", ""),
        ("Código descuento para la Semana del Hogar", "", ""),
        ("Una escapada de lujo", "Contenido patrocinado por la marca.", ""),
        ("Las 10 mejores sartenes calidad-precio", "", ""),
        ("El relleno nórdico ideal", "", "https://www.lavanguardia.com/comprar/hogar-cocina/2026/x"),
        (
            "Las tres hipotecas más baratas",
            "",
            "https://cincodias.elpais.com/herramientas/comparador-financiero/x",
        ),
    ],
)
def test_promotional_pieces(title, summary, url):
    assert is_promotional(title, summary, url)


@pytest.mark.parametrize(
    "title,summary,url",
    [
        ("Agenda del 19 al 25 de Octubre", "", ""),
        ("Hacienda ha rebajado la previsión de déficit al 2,5 %", "", "https://medio.test/economia/x"),
        ("El precio de la luz cae por debajo de 50 euros el megavatio hora", "", ""),
        ("Los pensionistas cobrarán 30 euros menos en noviembre", "", ""),
        ("Renfe ofrece un 50% de descuento en los abonos de Cercanías", "", ""),
        ("El Black Friday dispara las ventas del comercio un 12 %", "", ""),
        ("Los mejores momentos del Real Madrid - Barcelona", "", ""),
        ("Los mejores colegios de España, según el ranking de 2026", "", ""),
        ("Amazon anuncia 2.000 despidos en Europa", "", ""),
        ("La selección española golea a Georgia", "", "https://medio.test/deportes/seleccion-espanola/x"),
        ("El chollo de los diputados: dietas sin justificar", "", ""),
        ("Qué vivienda puedes comprar por 250.000 euros", "", "https://medio.test/economia/comprar-vivienda"),
    ],
)
def test_news_is_not_promotional(title, summary, url):
    assert not is_promotional(title, summary, url)


RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>El Congreso aprueba la ley de vivienda</title><link>https://tienda.test/politica/ley</link></item>
<item><title>Las mejores freidoras de aire por menos de 60 euros</title>
<link>https://tienda.test/tecnologia/freidoras</link></item>
<item><title>Un abrigo de plumas ideal</title><link>https://tienda.test/escaparate/moda/abrigo</link></item>
</channel></rss>"""


def test_crawl_skips_promotional_entries(session):
    spec = OutletSpec(
        slug="tienda",
        name="Tienda",
        homepage="https://tienda.test/",
        country="ES",
        language="es",
        scope="national",
        feeds=(FeedSpec("https://tienda.test/rss.xml", None),),
    )
    sync_registry(session, [spec])

    def server(request: httpx.Request) -> httpx.Response:
        if str(request.url) == "https://tienda.test/rss.xml":
            return httpx.Response(200, content=RSS)
        return httpx.Response(404)

    run = asyncio.run(
        crawl(
            session,
            replace(Settings(), per_domain_delay_seconds=0, fetch_full_text=False),
            transport=httpx.MockTransport(server),
        )
    )
    assert run.articles_new == 1 and run.stats["promotional_skipped"] == 2
    assert session.scalars(select(Article.title)).all() == ["El Congreso aprueba la ley de vivienda"]


def test_assign_stories_removes_stored_promotional_pieces(session):
    out = Outlet(slug="m", name="M", homepage="https://m", country="ES", language="es", scope="national")
    session.add(out)
    session.flush()
    now = utcnow()

    def add(i, title, story=None):
        a = Article(
            outlet_id=out.id,
            url=f"https://m/{i}",
            url_hash=f"{i:064d}",
            title=title,
            published_at=now - timedelta(minutes=i),
            language="es",
            country="ES",
            category="sociedad",
            topics=[],
            story_id=story.id if story else None,
        )
        session.add(a)
        return a

    promo_story = Story(title="x", category="sociedad", country="ES", first_seen=now, last_seen=now)
    session.add(promo_story)
    session.flush()
    add(1, "Los mejores cepillos de dientes eléctricos baratos por menos de 30€", promo_story)
    add(2, "Los mejores cepillos y pastas dentales para la higiene bucal de tu perro y gato", promo_story)
    add(3, "Un terremoto sacude Japón")
    session.flush()

    out = assign_stories(session, now=now)
    assert out["promotional_removed"] == 2 and out["articles"] == 1
    assert session.scalar(select(func.count(Article.id))) == 1
    # La historia que solo era publicidad desaparece; queda la de la noticia.
    assert session.scalars(select(Story.title)).all() == ["Un terremoto sacude Japón"]
