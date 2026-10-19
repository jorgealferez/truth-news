"""Sincronizacion del registro con la base y ejecucion de un rastreo completo."""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews.classify import classify, topics
from truthnews.config import Settings
from truthnews.crawler.extract import canonical_url, extract_text, sha256, word_count
from truthnews.crawler.feeds import FeedEntry, discover_feed_urls, parse_feed
from truthnews.crawler.http import PoliteClient
from truthnews.models import REVISION_MAX_CHARS, Article, ArticleRevision, CrawlRun, Feed, Outlet, utcnow
from truthnews.promo import is_promotional
from truthnews.registry import OutletSpec, load_outlets

log = logging.getLogger(__name__)
MAX_FEED_ERRORS = 5
# Secciones donde hay afirmaciones que contrastar con datos: su texto completo va primero.
VERIFIABLE = ("politica", "economia")
BACKFILL_WINDOW = timedelta(hours=24)
BACKFILL_PER_DOMAIN = 5
BACKFILL_DOMAIN_FAILURES = 2


def sync_registry(session: Session, specs: list[OutletSpec] | None = None) -> dict:
    """Crea o actualiza medios y feeds declarados. No borra: desactiva lo que salio del registro."""
    specs = specs if specs is not None else load_outlets()
    existing = {o.slug: o for o in session.scalars(select(Outlet))}
    feeds_by_url = {f.url: f for f in session.scalars(select(Feed))}
    created = updated = feeds_created = 0
    for spec in specs:
        outlet = existing.get(spec.slug)
        values = dict(
            name=spec.name,
            homepage=spec.homepage,
            country=spec.country,
            language=spec.language,
            scope=spec.scope,
            region=spec.region,
            city=spec.city,
            kind=spec.kind,
            owner=spec.owner,
            active=True,
        )
        if outlet is None:
            outlet = Outlet(slug=spec.slug, **values)
            session.add(outlet)
            created += 1
        else:
            for k, v in values.items():
                setattr(outlet, k, v)
            updated += 1
        session.flush()
        for fs in spec.feeds:
            feed = feeds_by_url.get(fs.url)
            if feed is None:
                feed = Feed(outlet_id=outlet.id, url=fs.url, category_hint=fs.category, discovered=False)
                session.add(feed)
                feeds_by_url[fs.url] = feed
                feeds_created += 1
            else:
                feed.category_hint = fs.category
    slugs = {s.slug for s in specs}
    deactivated = 0
    for slug, outlet in existing.items():
        if slug not in slugs and outlet.active:
            outlet.active = False
            deactivated += 1
    session.flush()
    return {
        "created": created,
        "updated": updated,
        "feeds_created": feeds_created,
        "deactivated": deactivated,
    }


@dataclass
class FeedResult:
    feed_id: int
    status: int | None = None
    entries: list[FeedEntry] = field(default_factory=list)
    error: str | None = None
    etag: str | None = None
    last_modified: str | None = None
    blocked: bool = False


async def _fetch_feed(client: PoliteClient, feed: Feed, limit: int) -> FeedResult:
    res = FeedResult(feed_id=feed.id)
    headers = {}
    if feed.etag:
        headers["If-None-Match"] = feed.etag
    if feed.last_modified:
        headers["If-Modified-Since"] = feed.last_modified
    try:
        resp = await client.get(feed.url, headers=headers)
    except (httpx.HTTPError, ValueError) as exc:
        res.error = f"{type(exc).__name__}: {exc}"[:500]
        return res
    if resp is None:
        res.blocked = True
        res.error = "robots.txt prohibe el acceso"
        return res
    res.status = resp.status_code
    if resp.status_code == 304:
        return res
    if resp.status_code >= 400:
        res.error = f"HTTP {resp.status_code}"
        return res
    entries, is_feed = parse_feed(resp.content, limit=limit)
    if not is_feed:
        res.error = "la respuesta no es un feed RSS/Atom"
        return res
    res.entries = entries
    res.etag = resp.headers.get("etag")
    res.last_modified = resp.headers.get("last-modified")
    return res


async def _discover(client: PoliteClient, outlet: Outlet) -> list[str]:
    try:
        resp = await client.get(outlet.homepage)
    except (httpx.HTTPError, ValueError):
        return []
    if resp is None or resp.status_code >= 400:
        return []
    return discover_feed_urls(resp.text, str(resp.url))


async def _fetch_text(client: PoliteClient, url: str) -> str | None:
    try:
        resp = await client.get(url)
    except (httpx.HTTPError, ValueError):
        return None
    if resp is None or resp.status_code >= 400 or "html" not in resp.headers.get("content-type", "html"):
        return None
    return await asyncio.to_thread(extract_text, resp.text, url)


async def backfill_texts(
    session: Session, client: PoliteClient, limit: int, now: datetime | None = None
) -> int:
    """Texto completo de los articulos recientes de secciones verificables que aun no lo tienen.

    Como mucho `limit` peticiones por ciclo y BACKFILL_PER_DOMAIN por medio; un dominio que falla dos
    veces (paywall, 403, timeout) se deja hasta el ciclo siguiente. Mismo cliente educado del rastreo.
    """
    since = (now or datetime.now(UTC)) - BACKFILL_WINDOW
    rows = session.scalars(
        select(Article)
        .where(
            Article.content_text.is_(None),
            Article.category.in_(VERIFIABLE),
            Article.published_at >= since,
        )
        .order_by(Article.published_at.desc())
        .limit(limit * 3)
    ).all()
    by_domain: dict[str, list[Article]] = defaultdict(list)
    picked = 0
    for art in rows:
        domain = urlsplit(art.url).netloc
        if picked < limit and len(by_domain[domain]) < BACKFILL_PER_DOMAIN:
            by_domain[domain].append(art)
            picked += 1

    async def one_domain(arts: list[Article]) -> list[tuple[Article, str]]:
        got, failures = [], 0
        for art in arts:
            text = await _fetch_text(client, art.url)
            if text:
                got.append((art, text))
            else:
                failures += 1
                if failures >= BACKFILL_DOMAIN_FAILURES:
                    break
        return got

    filled = 0
    for got in await asyncio.gather(*(one_domain(a) for a in by_domain.values())):
        for art, text in got:
            art.content_text, art.content_hash, art.word_count = text, sha256(text), word_count(text)
            filled += 1
    log.info("textos rellenados: %s de %s intentables", filled, picked)
    return filled


def _norm(text: str | None) -> str:
    return " ".join((text or "").split())


def track_revisions(session: Session, article: Article, entry: FeedEntry, run_id: int | None = None) -> int:
    """Guarda el antes y el despues si el medio cambio el titular o el extracto, y deja la noticia en
    su version vigente. Un extracto que desaparece del feed no es un cambio (los feeds lo recortan)."""
    n = 0
    for name, new in (("title", entry.title), ("summary", entry.summary)):
        old, new = _norm(getattr(article, name)), _norm(new)
        if not new or new == old:
            continue
        before, after = old[:REVISION_MAX_CHARS], new[:REVISION_MAX_CHARS]
        session.add(
            ArticleRevision(
                article_id=article.id,
                outlet_id=article.outlet_id,
                crawl_run_id=run_id,
                field=name,
                before=before,
                after=after,
                before_hash=sha256(old),
                after_hash=sha256(new),
            )
        )
        setattr(article, name, new)
        n += 1
    return n


async def crawl(
    session: Session,
    settings: Settings,
    transport: httpx.AsyncBaseTransport | None = None,
    outlet_slugs: list[str] | None = None,
) -> CrawlRun:
    run = CrawlRun(started_at=utcnow())
    session.add(run)
    session.flush()
    q = select(Outlet).where(Outlet.active.is_(True))
    if outlet_slugs:
        q = q.where(Outlet.slug.in_(outlet_slugs))
    outlets = list(session.scalars(q))
    async with PoliteClient(
        settings.user_agent,
        settings.per_domain_delay_seconds,
        concurrency=settings.crawl_concurrency,
        transport=transport,
    ) as client:
        # 1) Descubrimiento para medios sin feeds activos.
        needs = [o for o in outlets if not any(f.active for f in o.feeds)]
        discovered = await asyncio.gather(*(_discover(client, o) for o in needs))
        n_discovered = 0
        known = {f.url for f in session.scalars(select(Feed))}
        for outlet, urls in zip(needs, discovered, strict=True):
            for url in urls:
                if url not in known:
                    session.add(Feed(outlet_id=outlet.id, url=url, discovered=True))
                    known.add(url)
                    n_discovered += 1
        session.flush()
        for o in outlets:
            session.refresh(o)

        # 2) Feeds.
        feeds = [f for o in outlets for f in o.feeds if f.active]
        results = await asyncio.gather(
            *(_fetch_feed(client, f, settings.max_articles_per_feed) for f in feeds)
        )
        by_id = {f.id: f for f in feeds}
        outlet_by_id = {o.id: o for o in outlets}
        candidates: dict[str, tuple[Feed, FeedEntry]] = {}
        for res in results:
            feed = by_id[res.feed_id]
            feed.last_fetched_at = utcnow()
            feed.last_status = res.status
            if res.error:
                feed.error_count += 1
                feed.last_error = res.error
                if feed.error_count >= MAX_FEED_ERRORS:
                    feed.active = False
                run.feeds_failed += 1
                continue
            feed.error_count = 0
            feed.last_error = None
            feed.etag = (res.etag or "")[:300] or feed.etag
            feed.last_modified = res.last_modified or feed.last_modified
            run.feeds_ok += 1
            for entry in res.entries:
                url = canonical_url(entry.url)
                candidates.setdefault(sha256(url), (feed, entry))
        run.feeds_total = len(feeds)

        # 3) Articulos nuevos (deduplicados por url_hash); en los ya conocidos, cambios de titular o
        # extracto (ADR 0015).
        existing: set[str] = set()
        hashes = list(candidates)
        n_revisions = 0
        for i in range(0, len(hashes), 500):
            batch = hashes[i : i + 500]
            for known_art in session.scalars(select(Article).where(Article.url_hash.in_(batch))):
                existing.add(known_art.url_hash)
                n_revisions += track_revisions(session, known_art, candidates[known_art.url_hash][1], run.id)
        new_items = [(h, feed, entry) for h, (feed, entry) in candidates.items() if h not in existing]
        # Guias de compra, ofertas y contenido patrocinado de los medios no son noticias: no se guardan.
        n_promo = len(new_items)
        new_items = [it for it in new_items if not is_promotional(it[2].title, it[2].summary, it[2].url)]
        n_promo -= len(new_items)
        texts: list[str | None] = [None] * len(new_items)
        cats = [
            classify(e.title, e.summary, e.url, e.tags, outlet_by_id[f.outlet_id].language, f.category_hint)
            for _, f, e in new_items
        ]
        if settings.fetch_full_text and new_items:
            epoch = datetime.min.replace(tzinfo=UTC)
            order = sorted(  # politica y economia primero; dentro, lo mas reciente
                range(len(new_items)),
                key=lambda i: (cats[i] in VERIFIABLE, new_items[i][2].published_at or epoch),
                reverse=True,
            )[: settings.max_text_fetch_per_run]
            fetched = await asyncio.gather(
                *(_fetch_text(client, canonical_url(new_items[i][2].url)) for i in order)
            )
            for i, text in zip(order, fetched, strict=True):
                texts[i] = text
        now = datetime.now(UTC)
        for (h, feed, entry), text, category in zip(new_items, texts, cats, strict=True):
            outlet = outlet_by_id[feed.outlet_id]
            published = entry.published_at or now
            if published > now:
                published = now
            session.add(
                Article(
                    outlet_id=outlet.id,
                    feed_id=feed.id,
                    url=canonical_url(entry.url),
                    url_hash=h,
                    title=entry.title,
                    summary=entry.summary or None,
                    content_text=text,
                    author=entry.author,
                    image_url=entry.image_url,
                    published_at=published,
                    language=outlet.language,
                    country=outlet.country,
                    region=outlet.region,
                    category=category,
                    topics=topics(entry.title, entry.tags),
                    content_hash=sha256(text) if text else None,
                    word_count=word_count(text),
                )
            )
        session.flush()
        backfilled = 0
        if settings.fetch_full_text and settings.max_text_backfill_per_run > 0:
            backfilled = await backfill_texts(session, client, settings.max_text_backfill_per_run)
        run.articles_new = len(new_items)
        run.robots_blocked = client.robots_blocked
        run.stats = {
            "outlets": len(outlets),
            "feeds_discovered": n_discovered,
            "with_full_text": sum(1 for t in texts if t),
            "outlets_with_new": len({by_id[f.id].outlet_id for _, f, _ in new_items}),
            "revisions": n_revisions,
            "texts_backfilled": backfilled,
            "promotional_skipped": n_promo,
        }
    run.finished_at = utcnow()
    session.flush()
    log.info(
        "rastreo %s: %s feeds ok, %s fallidos, %s articulos nuevos, %s cambios de titular o extracto",
        run.id,
        run.feeds_ok,
        run.feeds_failed,
        run.articles_new,
        run.stats.get("revisions", 0),
    )
    return run
