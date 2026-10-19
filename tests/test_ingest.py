import asyncio
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from pathlib import Path

import httpx
from sqlalchemy import func, select

from truthnews.config import Settings
from truthnews.crawler.http import PoliteClient
from truthnews.crawler.ingest import MAX_FEED_ERRORS, backfill_texts, crawl, sync_registry
from truthnews.models import Article, ArticleRevision, Feed, Outlet
from truthnews.registry import FeedSpec, OutletSpec

FEED = (Path(__file__).parent / "fixtures" / "feed.xml").read_bytes()
ARTICLE_HTML = (
    "<html><body><article>"
    + "<p>Texto del articulo con datos y cifras reales. </p>" * 30
    + "</article></body></html>"
)


def settings(**kw) -> Settings:
    return replace(Settings(), per_domain_delay_seconds=0, **kw)


SPECS = [
    OutletSpec(
        slug="medio",
        name="Medio",
        homepage="https://medio.test/",
        country="ES",
        language="es",
        scope="regional",
        region="ES-AN",
        feeds=(FeedSpec("https://medio.test/rss.xml", None),),
    ),
    OutletSpec(
        slug="descubre",
        name="Descubre",
        homepage="https://descubre.test/",
        country="ES",
        language="es",
        scope="national",
    ),
    OutletSpec(
        slug="roto",
        name="Roto",
        homepage="https://roto.test/",
        country="ES",
        language="es",
        scope="national",
        feeds=(FeedSpec("https://roto.test/rss.xml", "economia"),),
    ),
]


class Server:
    def __init__(self):
        self.hits: list[str] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.hits.append(url)
        host = request.url.host
        if url.endswith("/robots.txt"):
            if host == "medio.test":
                return httpx.Response(200, text="User-agent: *\nDisallow: /privado/\n")
            return httpx.Response(404)
        if url == "https://medio.test/rss.xml":
            if request.headers.get("if-none-match") == '"v1"':
                return httpx.Response(304)
            return httpx.Response(200, content=FEED, headers={"etag": '"v1"'})
        if url == "https://descubre.test/":
            return httpx.Response(200, html='<link rel="alternate" type="application/rss+xml" href="/feed">')
        if url == "https://descubre.test/feed":
            return httpx.Response(200, content=FEED.replace(b"medio.test", b"descubre.test"))
        if url == "https://roto.test/rss.xml":
            return httpx.Response(500)
        if host in ("medio.test", "descubre.test"):
            return httpx.Response(200, html=ARTICLE_HTML)
        return httpx.Response(404)


def test_sync_registry_is_idempotent_and_deactivates(session):
    first = sync_registry(session, SPECS)
    assert first == {"created": 3, "updated": 0, "feeds_created": 2, "deactivated": 0}
    again = sync_registry(session, SPECS)
    assert again["created"] == 0 and again["updated"] == 3 and again["feeds_created"] == 0
    gone = sync_registry(session, SPECS[:1])
    assert gone["deactivated"] == 2
    assert session.scalar(select(func.count(Outlet.id)).where(Outlet.active.is_(True))) == 1


def test_crawl_end_to_end(session):
    sync_registry(session, SPECS)
    server = Server()
    run = asyncio.run(crawl(session, settings(), transport=httpx.MockTransport(server)))
    # medio: 2 utiles (la tercera esta prohibida por robots solo para el texto) + descubre: 3; roto falla.
    assert run.feeds_total == 3 and run.feeds_ok == 2 and run.feeds_failed == 1
    assert run.stats["feeds_discovered"] == 1
    assert run.articles_new == 6
    assert "https://medio.test/privado/x" not in server.hits  # robots.txt respetado
    assert run.robots_blocked == 1
    arts = {a.url: a for a in session.scalars(select(Article))}
    decreto = arts["https://medio.test/politica/decreto"]
    assert decreto.category == "politica" and decreto.region == "ES-AN" and decreto.word_count > 50
    assert decreto.topics == ["Vivienda"]
    assert arts["https://medio.test/privado/x"].content_text is None
    roto = session.scalars(select(Feed).where(Feed.url == "https://roto.test/rss.xml")).one()
    assert roto.error_count == 1 and roto.last_error == "HTTP 500"

    # Segundo rastreo: 304 para medio, sin duplicados.
    run2 = asyncio.run(crawl(session, settings(fetch_full_text=False), transport=httpx.MockTransport(server)))
    assert run2.articles_new == 0 and run2.stats["revisions"] == 0
    assert session.scalar(select(func.count(Article.id))) == 6


def test_crawl_tracks_title_and_summary_changes(session):
    """ADR 0015: si el medio cambia titular o extracto se guarda el antes y el despues con su huella."""
    sync_registry(session, SPECS[1:2])  # descubre.test: feed sin etag, se relee entero en cada ciclo
    server = Server()
    asyncio.run(crawl(session, settings(fetch_full_text=False), transport=httpx.MockTransport(server)))
    changed = FEED.replace(
        b"El IPC sube al 3,1 % en septiembre", b"El IPC sube al 3,4 % en septiembre"
    ).replace(b"La inflaci\xc3\xb3n repunta.", b"La inflaci\xc3\xb3n repunta con fuerza.")

    def edited(request):
        if str(request.url) == "https://descubre.test/feed":
            return httpx.Response(200, content=changed.replace(b"medio.test", b"descubre.test"))
        return server(request)

    run = asyncio.run(crawl(session, settings(fetch_full_text=False), transport=httpx.MockTransport(edited)))
    assert run.articles_new == 0 and run.stats["revisions"] == 2
    ipc = session.scalars(select(Article).where(Article.url == "https://descubre.test/economia/ipc")).one()
    assert ipc.title == "El IPC sube al 3,4 % en septiembre"  # la noticia muestra la version vigente
    revs = {r.field: r for r in session.scalars(select(ArticleRevision))}
    assert revs["title"].before == "El IPC sube al 3,1 % en septiembre"
    assert revs["title"].after == ipc.title and revs["title"].outlet_id == ipc.outlet_id
    assert revs["title"].crawl_run_id == run.id and len(revs["title"].before_hash) == 64
    assert revs["summary"].after == "La inflación repunta con fuerza."
    # Un tercer ciclo igual no repite revisiones.
    again = asyncio.run(
        crawl(session, settings(fetch_full_text=False), transport=httpx.MockTransport(edited))
    )
    assert again.stats["revisions"] == 0


def test_text_fetch_cap_prefers_newest(session):
    sync_registry(session, SPECS[:1])
    run = asyncio.run(
        crawl(
            session,
            settings(max_text_fetch_per_run=1, max_text_backfill_per_run=0),
            transport=httpx.MockTransport(Server()),
        )
    )
    assert run.stats["with_full_text"] == 1
    with_text = [a.url for a in session.scalars(select(Article)) if a.content_text]
    assert with_text == ["https://medio.test/politica/decreto"]  # la mas reciente


class RecentServer(Server):
    """El feed de prueba con fechas de la ultima hora: el relleno solo mira las ultimas 24 h y las fechas
    fijas del fixture (18/10/2026) caducaban en cuanto pasaba un dia."""

    def __call__(self, request: httpx.Request) -> httpx.Response:
        resp = super().__call__(request)
        if str(request.url) == "https://medio.test/rss.xml" and resp.status_code == 200:
            now = datetime.now(UTC)
            content = FEED.replace(
                b"Sun, 18 Oct 2026 10:00:00 +0200", format_datetime(now - timedelta(hours=1)).encode()
            ).replace(b"Sun, 18 Oct 2026 09:00:00 +0200", format_datetime(now - timedelta(hours=2)).encode())
            return httpx.Response(200, content=content, headers={"etag": '"v1"'})
        return resp


def test_backfill_fills_recent_verifiable_articles_without_text(session):
    sync_registry(session, SPECS[:1])
    server = RecentServer()
    run = asyncio.run(
        crawl(session, settings(max_text_fetch_per_run=0), transport=httpx.MockTransport(server))
    )
    arts = {a.url: a for a in session.scalars(select(Article))}
    filled = {u for u, a in arts.items() if a.content_text}
    assert run.stats["with_full_text"] == 0 and run.stats["texts_backfilled"] == len(filled) >= 1
    assert all(arts[u].category in ("politica", "economia") for u in filled)
    assert all(arts[u].word_count > 50 and arts[u].content_hash for u in filled)
    assert "https://medio.test/privado/x" not in server.hits  # robots.txt sigue mandando
    again = asyncio.run(
        crawl(session, settings(max_text_fetch_per_run=0), transport=httpx.MockTransport(RecentServer()))
    )
    assert again.stats["texts_backfilled"] == 0  # lo que ya tiene texto no se vuelve a pedir


def test_backfill_gives_up_on_a_failing_domain(session):
    sync_registry(session, SPECS[:1])
    o = session.scalars(select(Outlet)).one()
    now = datetime.now(UTC)
    for i in range(4):
        session.add(
            Article(
                outlet_id=o.id,
                url=f"https://caido.test/politica/{i}",
                url_hash=f"c{i}".ljust(64, "0"),
                title=f"t{i}",
                published_at=now,
                language="es",
                country="ES",
                category="politica",
            )
        )
    session.commit()
    hits = []

    def handler(request):
        hits.append(str(request.url))
        return httpx.Response(404) if request.url.path == "/robots.txt" else httpx.Response(503)

    async def go():
        async with PoliteClient("ua", 0, transport=httpx.MockTransport(handler)) as client:
            return await backfill_texts(session, client, limit=10)

    assert asyncio.run(go()) == 0
    assert len([h for h in hits if "/politica/" in h]) == 2  # dos fallos y se deja el dominio


def test_feed_deactivated_after_repeated_errors(session):
    sync_registry(session, SPECS[2:])
    for _ in range(MAX_FEED_ERRORS):
        asyncio.run(crawl(session, settings(fetch_full_text=False), transport=httpx.MockTransport(Server())))
    roto = session.scalars(select(Feed)).one()
    assert not roto.active


def test_crawl_filters_by_slug_and_handles_network_errors(session):
    sync_registry(session, SPECS)

    def boom(request):
        raise httpx.ConnectError("sin red", request=request)

    run = asyncio.run(crawl(session, settings(), transport=httpx.MockTransport(boom), outlet_slugs=["medio"]))
    assert run.feeds_total == 1 and run.feeds_failed == 1 and run.articles_new == 0


def test_robots_rules():
    def handler(request):
        if request.url.host == "cerrado.test":
            return httpx.Response(503)
        if request.url.host == "abierto.test":
            return httpx.Response(403)
        return httpx.Response(200, text="User-agent: *\nDisallow: /\n")

    async def go():
        async with PoliteClient("Bot", 0, transport=httpx.MockTransport(handler)) as c:
            return (
                await c.allowed("https://cerrado.test/a"),
                await c.allowed("https://abierto.test/a"),
                await c.get("https://todo.test/a"),
                c.robots_blocked,
            )

    cerrado, abierto, todo, blocked = asyncio.run(go())
    assert cerrado is False and abierto is True and todo is None and blocked == 1


def test_non_feed_and_robots_blocked_feed(session):
    spec = [
        OutletSpec(
            slug="html",
            name="H",
            homepage="https://h.test/",
            country="ES",
            language="es",
            scope="national",
            feeds=(FeedSpec("https://h.test/no-feed", None), FeedSpec("https://h.test/bloq/rss", None)),
        )
    ]
    sync_registry(session, spec)

    def handler(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /bloq/\n")
        return httpx.Response(200, html="<html>nada</html>")

    run = asyncio.run(crawl(session, settings(), transport=httpx.MockTransport(handler)))
    errors = sorted(f.last_error for f in session.scalars(select(Feed)))
    assert run.feeds_failed == 2
    assert errors == ["la respuesta no es un feed RSS/Atom", "robots.txt prohibe el acceso"]
