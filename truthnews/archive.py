"""Importacion de noticias antiguas del archivo (ADR 0028): mas informacion anterior de las mismas personas.

Por cada entidad, de las mas presentes a las menos, se pide a la hemeroteca de GDELT (desde 2017) un
mes hacia atras cada vez y se guardan solo las noticias de medios del registro, marcadas con
`origin = 'archivo'`: titular, fecha y enlace (lo que GDELT publica); no se descarga la pagina, igual
que con el rastreo se cita sin republicar (ADR 0003). `entity.archived_until` recuerda hasta donde se
ha llegado. Lo importado no se verifica contra el dato de hoy (seria juzgar 2019 con 2026): solo
alimenta las fichas de entidad, la linea temporal y los hilos.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from truthnews.classify import classify, topics
from truthnews.crawler.extract import canonical_url, sha256
from truthnews.data import gdelt
from truthnews.models import Article, Entity, Mention, Outlet, utcnow

log = logging.getLogger(__name__)
FLOOR = datetime(2017, 1, 1, tzinfo=UTC)  # GDELT DOC no tiene archivo anterior
WINDOW = timedelta(days=30)
MAX_RECORDS = 75
MIN_OUTLETS = 3  # una entidad descubierta entra en el archivo cuando ya la nombran 3 medios
ARCHIVE_KINDS = ("persona", "partido", "institucion", "organizacion")
_GDELT_COUNTRY = {"ES": "spain"}  # medido: "sourcecountry:spain" filtra prensa espanola
_LANG = {"spanish": "es", "english": "en", "portuguese": "pt", "catalan": "ca", "french": "fr"}


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def host(url: str) -> str:
    h = urlsplit(url if "//" in url else f"//{url}").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def outlet_hosts(session: Session) -> dict[str, Outlet]:
    return {host(o.homepage): o for o in session.scalars(select(Outlet).where(Outlet.active.is_(True)))}


def query_for(entity: Entity) -> str:
    q = f'"{entity.name}"'
    country = _GDELT_COUNTRY.get(entity.country or "ES")
    return f"{q} sourcecountry:{country}" if country else q


def candidates(session: Session, limit: int) -> list[Entity]:
    """Entidades por importar: primero las que nunca se han importado, despues las mas nombradas."""
    return list(
        session.scalars(
            select(Entity)
            .where(
                Entity.kind.in_(ARCHIVE_KINDS),
                or_(Entity.curated.is_(True), Entity.n_outlets >= MIN_OUTLETS),
                Entity.n_articles > 0,
                or_(Entity.archived_until.is_(None), Entity.archived_until > FLOOR),
            )
            .order_by(Entity.archived_until.is_not(None), Entity.n_articles.desc(), Entity.id)
            .limit(limit)
        )
    )


def _window_end(session: Session, entity: Entity, now: datetime) -> datetime:
    if entity.archived_until is not None:
        return _aware(entity.archived_until)
    oldest = session.scalar(select(func.min(Mention.published_at)).where(Mention.entity_id == entity.id))
    return min(_aware(oldest), now) if oldest else now


def import_entity(
    session: Session,
    entity: Entity,
    hosts: dict[str, Outlet],
    now: datetime | None = None,
    fetch: Callable[..., list[dict]] = gdelt.articles,
) -> dict:
    """Importa un mes de archivo de `entity` hacia atras y mueve su cursor."""
    now = now or utcnow()
    end = _window_end(session, entity, now)
    start = max(end - WINDOW, FLOOR)
    # Si GDELT no responde se lanza Unavailable: el cursor no se mueve y ese mes se pide otra vez.
    found = fetch(query_for(entity), start, end, max_records=MAX_RECORDS, strict=True)
    rows = []
    for item in found:
        outlet = hosts.get(host(item.get("domain") or item.get("url", "")))
        title = (item.get("title") or "").strip()
        if outlet is None or not title or not item.get("url"):
            continue
        url = canonical_url(item["url"])
        rows.append((sha256(url), url, title, _aware(item["date"]), outlet, item.get("language", "")))
    known = set()
    hashes = [r[0] for r in rows]
    if hashes:
        known = set(session.scalars(select(Article.url_hash).where(Article.url_hash.in_(hashes))))
    new = 0
    for h, url, title, published, outlet, lang in rows:
        if h in known:
            continue
        known.add(h)
        language = _LANG.get(lang.lower(), outlet.language)
        session.add(
            Article(
                outlet_id=outlet.id,
                url=url,
                url_hash=h,
                title=title[:600],
                published_at=min(published, now),
                language=language,
                country=outlet.country,
                region=outlet.region,
                category=classify(title, "", url, None, language),
                topics=topics(title, None),
                origin="archivo",
            )
        )
        new += 1
    entity.archived_until = start
    session.flush()
    return {
        "entity": entity.name,
        "from": f"{start:%Y-%m-%d}",
        "to": f"{end:%Y-%m-%d}",
        "found": len(found),
        "new": new,
    }


def run(
    session: Session,
    budget: int = 6,
    now: datetime | None = None,
    fetch: Callable[..., list[dict]] = gdelt.articles,
    clock: Callable[[], float] = time.monotonic,
    max_seconds: float = 90.0,
) -> dict:
    """Hasta `budget` consultas al archivo (GDELT pide 5 s entre ellas) sin pasar de `max_seconds`."""
    hosts = outlet_hosts(session)
    began = clock()
    done = []
    for entity in candidates(session, budget):
        if clock() - began > max_seconds:
            break
        try:
            with session.begin_nested():  # una consulta fallida no deshace las anteriores ni mueve el cursor
                done.append(import_entity(session, entity, hosts, now, fetch))
        except Exception as exc:  # una consulta fallida no tumba el ciclo
            log.warning("archivo: %s fallo: %s", entity.name, exc)
            break
    out = {"queries": len(done), "new": sum(d["new"] for d in done), "detail": done}
    log.info("archivo: %s consultas, %s noticias nuevas", out["queries"], out["new"])
    return out
