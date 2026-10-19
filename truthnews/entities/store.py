"""Guardado de entidades y menciones por tandas, y atribucion de cada afirmacion a quien la dice (ADR 0028).

El worker procesa en cada ciclo las noticias aun sin extraer, de las mas recientes a las mas antiguas,
hasta `limit`. Reprocesar una noticia (p. ej. tras mejorar el extractor) reescribe sus menciones.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from truthnews.entities.extract import Found, extract, known, speaker_of
from truthnews.models import Article, Claim, Entity, Mention, utcnow

log = logging.getLogger(__name__)
BATCH = 2000
_CHUNK = 500


def sync_curated(session: Session) -> int:
    """Alta o actualizacion de las entidades del registro curado."""
    reg = {k.key: k for k in known()}
    existing = {e.key: e for e in _by_keys(session, reg)}
    for key, k in reg.items():
        e = existing.get(key)
        if e is None:
            e = Entity(key=key, kind=k.kind, name=k.name, n_mentions=0, n_articles=0, n_outlets=0)
            session.add(e)
        e.name, e.country, e.aliases, e.curated = k.name, k.country, list(k.aliases), True
    session.flush()
    return len(reg)


def _by_keys(session: Session, keys: Iterable[str]) -> list[Entity]:
    keys = list(keys)
    out: list[Entity] = []
    for i in range(0, len(keys), _CHUNK):
        out += session.scalars(select(Entity).where(Entity.key.in_(keys[i : i + _CHUNK])))
    return out


def _entities_for(session: Session, found: Iterable[Found], now: datetime) -> dict[str, Entity]:
    found = {f.key: f for f in found}
    cache = {e.key: e for e in _by_keys(session, found)}
    for key, f in found.items():
        if key not in cache:
            cache[key] = Entity(
                key=key,
                kind=f.kind,
                name=f.name,
                country=f.country,
                aliases=[],
                curated=f.curated,
                n_mentions=0,
                n_articles=0,
                n_outlets=0,
                created_at=now,
                updated_at=now,
            )
            session.add(cache[key])
    session.flush()
    return cache


def process(session: Session, limit: int = BATCH, now: datetime | None = None) -> dict:
    """Extrae entidades de hasta `limit` noticias pendientes y atribuye sus afirmaciones."""
    now = now or utcnow()
    arts = list(
        session.scalars(
            select(Article).where(Article.entities_at.is_(None)).order_by(Article.id.desc()).limit(limit)
        )
    )
    if not arts:
        return {"articles": 0, "mentions": 0, "entities_new": 0, "speakers": 0}
    sync_curated(session)
    before = session.scalar(select(func.count(Entity.id))) or 0
    extracted = {a.id: extract(a.title, f"{a.summary or ''}\n{a.content_text or ''}") for a in arts}
    entities = _entities_for(session, (f for fs in extracted.values() for f in fs), now)
    ids = [a.id for a in arts]
    for i in range(0, len(ids), _CHUNK):
        session.execute(delete(Mention).where(Mention.article_id.in_(ids[i : i + _CHUNK])))
    n_mentions = 0
    for a in arts:
        for f in extracted[a.id]:
            session.add(
                Mention(
                    entity_id=entities[f.key].id,
                    article_id=a.id,
                    outlet_id=a.outlet_id,
                    story_id=a.story_id,
                    published_at=a.published_at,
                    count=f.count,
                    role="dice" if f.speaks else "menciona",
                    quote=f.quote if f.speaks else None,
                )
            )
            n_mentions += 1
        a.entities_at = now
    session.flush()
    speakers = attribute_claims(session, ids, entities)
    refresh_counts(session, [e.id for e in entities.values()], now)
    out = {
        "articles": len(arts),
        "mentions": n_mentions,
        "entities_new": (session.scalar(select(func.count(Entity.id))) or 0) - before,
        "speakers": speakers,
    }
    log.info("entidades: %s", out)
    return out


def attribute_claims(session: Session, article_ids: list[int], entities: dict[str, Entity]) -> int:
    """Pone `speaker_entity_id` a las afirmaciones de esas noticias cuya frase dice quien habla."""
    n = 0
    for i in range(0, len(article_ids), _CHUNK):
        for claim in session.scalars(
            select(Claim).where(
                Claim.article_id.in_(article_ids[i : i + _CHUNK]), Claim.speaker_entity_id.is_(None)
            )
        ):
            who = speaker_of(claim.text)
            if who is None:
                continue
            ent = entities.get(who.key) or _entities_for(session, [who], utcnow())[who.key]
            claim.speaker_entity_id = ent.id
            n += 1
    session.flush()
    return n


def refresh_counts(session: Session, entity_ids: list[int], now: datetime | None = None) -> None:
    """Recalcula menciones, noticias, medios y fechas de esas entidades desde `mention`."""
    now = now or utcnow()
    for i in range(0, len(entity_ids), _CHUNK):
        chunk = entity_ids[i : i + _CHUNK]
        rows = session.execute(
            select(
                Mention.entity_id,
                func.sum(Mention.count),
                func.count(Mention.id),
                func.count(func.distinct(Mention.outlet_id)),
                func.min(Mention.published_at),
                func.max(Mention.published_at),
            )
            .where(Mention.entity_id.in_(chunk))
            .group_by(Mention.entity_id)
        )
        seen = set()
        for eid, n_m, n_a, n_o, first, last in rows:
            e = session.get(Entity, eid)
            e.n_mentions, e.n_articles, e.n_outlets = int(n_m or 0), n_a, n_o
            e.first_seen, e.last_seen, e.updated_at = first, last, now
            seen.add(eid)
        for eid in set(chunk) - seen:
            e = session.get(Entity, eid)
            e.n_mentions = e.n_articles = e.n_outlets = 0
    session.flush()
