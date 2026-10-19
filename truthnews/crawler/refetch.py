"""Segunda captura del texto completo para ver si un medio cambio una cifra en el cuerpo (ADR 0032; decision
de la direccion 2026-10-19, opcion (a) acotada).

El rastreador descarga el texto completo una sola vez (`ingest.backfill_texts`). Aqui, fuera del nucleo de
ingest, se vuelve a descargar **una sola vez** el texto de unos pocos articulos que importan: los de
historias con cifras en disputa o con alguna verificacion, publicados hace entre 6 y 24 h. Si cambian las
frases con cifra, se guarda la revision `content` (antes y despues de esas frases, recortadas) y la noticia
queda en su version vigente. Limites: REFETCH_PER_CYCLE peticiones por ciclo, REFETCH_PER_DOMAIN por medio,
robots.txt y ritmo del cliente educado, sin reintentos y como mucho REFETCH_MAX_SECONDS por ciclo.
Lo ya re-descargado se apunta en `CrawlRun.stats["refetched"]` (sin esquema nuevo).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews.analysis.compare import figures
from truthnews.crawler.extract import sha256, word_count
from truthnews.crawler.http import PoliteClient
from truthnews.crawler.ingest import _fetch_text
from truthnews.models import (
    REVISION_MAX_CHARS,
    Article,
    ArticleRevision,
    Claim,
    CrawlRun,
    Story,
    Verification,
)

log = logging.getLogger(__name__)

REFETCH_MIN_AGE = timedelta(hours=6)
REFETCH_MAX_AGE = timedelta(hours=24)
REFETCH_PER_CYCLE = 20
REFETCH_PER_DOMAIN = 3
REFETCH_MAX_SECONDS = 60.0
MARK = "refetched"  # CrawlRun.stats: ids de articulos ya re-descargados
_SPLIT = re.compile(r"(?<=[.!?…])\s+")


def figure_sentences(text: str | None) -> str:
    """Las frases del texto que dan una cifra contable, en orden, recortadas al limite de las revisiones."""
    out = [s.strip() for s in _SPLIT.split(text or "") if s.strip() and figures(s)]
    return " ".join(out)[:REVISION_MAX_CHARS]


def already_refetched(session: Session, now: datetime) -> set[int]:
    since = now - REFETCH_MAX_AGE - timedelta(hours=6)
    done: set[int] = set()
    for (stats,) in session.execute(select(CrawlRun.stats).where(CrawlRun.started_at >= since)):
        done.update((stats or {}).get(MARK, []))
    return done


def candidates(session: Session, now: datetime, limit: int = REFETCH_PER_CYCLE) -> list[Article]:
    """Articulos con texto de historias con cifras en disputa o verificadas, en la ventana de 6-24 h."""
    verified = set(
        session.scalars(
            select(Claim.story_id)
            .join(Verification, Verification.claim_id == Claim.id)
            .where(Claim.story_id.is_not(None))
        )
    )
    disputed = {
        sid
        for sid, contrast in session.execute(
            select(Story.id, Story.contrast).where(
                Story.last_seen >= now - REFETCH_MAX_AGE - timedelta(hours=6)
            )
        )
        if contrast and contrast.get("disputas")
    }
    story_ids = verified | disputed
    if not story_ids:
        return []
    done = already_refetched(session, now)
    rows = session.scalars(
        select(Article)
        .where(
            Article.story_id.in_(story_ids),
            Article.content_text.is_not(None),
            Article.published_at >= now - REFETCH_MAX_AGE,
            Article.published_at <= now - REFETCH_MIN_AGE,
        )
        .order_by(Article.published_at.desc())
    ).all()
    per_domain: dict[str, int] = defaultdict(int)
    out = []
    for art in rows:
        domain = urlsplit(art.url).netloc
        if art.id in done or per_domain[domain] >= REFETCH_PER_DOMAIN:
            continue
        per_domain[domain] += 1
        out.append(art)
        if len(out) >= limit:
            break
    return out


async def refetch(
    session: Session, client: PoliteClient, run_id: int | None, now: datetime | None = None
) -> dict:
    now = now or datetime.now(UTC)
    started = time.monotonic()
    arts = candidates(session, now)
    by_domain: dict[str, list[Article]] = defaultdict(list)
    for art in arts:
        by_domain[urlsplit(art.url).netloc].append(art)

    async def one_domain(items: list[Article]) -> list[tuple[Article, str | None]]:
        return [(art, await _fetch_text(client, art.url)) for art in items]  # sin reintentos

    results: list[tuple[Article, str | None]] = []
    try:
        for got in await asyncio.wait_for(
            asyncio.gather(*(one_domain(v) for v in by_domain.values())), timeout=REFETCH_MAX_SECONDS
        ):
            results += got
    except TimeoutError:
        log.warning("re-descarga: se agoto el tiempo (%ss)", REFETCH_MAX_SECONDS)
    changed = fetched = 0
    for art, text in results:
        if not text:
            continue
        fetched += 1
        before, after = figure_sentences(art.content_text), figure_sentences(text)
        if before != after:
            session.add(
                ArticleRevision(
                    article_id=art.id,
                    outlet_id=art.outlet_id,
                    crawl_run_id=run_id,
                    field="content",
                    before=before,
                    after=after,
                    before_hash=sha256(before),
                    after_hash=sha256(after),
                    detected_at=now,
                )
            )
            changed += 1
        art.content_text, art.content_hash, art.word_count = text, sha256(text), word_count(text)
    stats = {
        "tried": len(arts),
        "fetched": fetched,
        "changed": changed,
        "seconds": round(time.monotonic() - started, 1),
    }
    run = session.get(CrawlRun, run_id) if run_id is not None else None
    if run is not None:  # todos los intentados cuentan como hechos: no se reintenta
        run.stats = {**(run.stats or {}), MARK: [a.id for a in arts], "refetch": stats}
    session.flush()
    log.info("re-descarga de textos: %s", stats)
    return stats


def run(session: Session, settings, run_id: int | None) -> dict:
    async def go() -> dict:
        async with PoliteClient(settings.user_agent, settings.per_domain_delay_seconds) as client:
            return await refetch(session, client, run_id)

    return asyncio.run(go())
