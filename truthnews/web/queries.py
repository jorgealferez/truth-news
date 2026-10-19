"""Consultas de lectura de la web: listados indexados por fecha con filtros de segmento."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from truthnews.models import (
    Article,
    ArticleRevision,
    Claim,
    CrawlRun,
    Outlet,
    Piece,
    Story,
    Thread,
    Topic,
    Verification,
)

PAGE_SIZE = 30


def latest(
    session: Session,
    *,
    category: str | None = None,
    country: str | None = None,
    region: str | None = None,
    outlet_id: int | None = None,
    page: int = 1,
    limit: int = PAGE_SIZE,
) -> list[Article]:
    q = select(Article).options(joinedload(Article.outlet))
    if category:
        q = q.where(Article.category == category)
    if country:
        q = q.where(Article.country == country)
    if region:
        q = q.where(Article.region == region)
    if outlet_id:
        q = q.where(Article.outlet_id == outlet_id)
    q = (
        q.order_by(Article.published_at.desc(), Article.id.desc())
        .limit(limit)
        .offset((max(page, 1) - 1) * limit)
    )
    return list(session.scalars(q))


def outlets(session: Session, country: str | None = None) -> list[tuple[Outlet, int]]:
    counts = (
        select(Article.outlet_id, func.count(Article.id).label("n")).group_by(Article.outlet_id).subquery()
    )
    q = (
        select(Outlet, func.coalesce(counts.c.n, 0))
        .outerjoin(counts, counts.c.outlet_id == Outlet.id)
        .where(Outlet.active.is_(True))
        .order_by(Outlet.country, Outlet.scope, Outlet.name)
    )
    if country:
        q = q.where(Outlet.country == country)
    return [(o, n) for o, n in session.execute(q)]


def totals(session: Session) -> dict:
    last = session.scalars(select(CrawlRun).order_by(CrawlRun.id.desc()).limit(1)).first()
    return {
        "stories": session.scalar(select(func.count(Story.id)).where(Story.n_outlets >= 2)) or 0,
        "claims": session.scalar(select(func.count(Claim.id))) or 0,
        "articles": session.scalar(select(func.count(Article.id))) or 0,
        "outlets": session.scalar(select(func.count(Outlet.id)).where(Outlet.active.is_(True))) or 0,
        "last_crawl": last.finished_at if last else None,
    }


def top_stories(
    session: Session,
    *,
    country: str | None = None,
    category: str | None = None,
    min_outlets: int = 2,
    hours: int = 48,
    limit: int = 20,
    offset: int = 0,
) -> list[Story]:
    """Historias multimedio recientes o relanzadas; primero lo que tiene datos que difieren (ADR 0012)."""
    since = datetime.now(UTC) - timedelta(hours=hours)
    q = select(Story).where(
        Story.n_outlets >= min_outlets, or_(Story.last_seen >= since, Story.relaunched_at >= since)
    )
    if country:
        q = q.where(Story.country == country)
    if category:
        q = q.where(Story.category == category)
    q = q.order_by(Story.priority.desc(), Story.id.desc())  # recorre ix_story_country_priority
    q = q.limit(limit).offset(offset)
    return list(session.scalars(q))


def story_articles(session: Session, story_id: int) -> list[Article]:
    q = (
        select(Article)
        .options(joinedload(Article.outlet))
        .where(Article.story_id == story_id)
        .order_by(Article.published_at)
    )
    return list(session.scalars(q))


def story_outlet_names(session: Session, story_ids: list[int]) -> dict[int, list[str]]:
    if not story_ids:
        return {}
    rows = session.execute(
        select(Article.story_id, Outlet.name)
        .join(Outlet, Outlet.id == Article.outlet_id)
        .where(Article.story_id.in_(story_ids))
        .distinct()
    )
    out: dict[int, list[str]] = {}
    for sid, name in rows:
        out.setdefault(sid, []).append(name)
    return {k: sorted(v) for k, v in out.items()}


def claims_for_story(session: Session, story_id: int) -> list[Claim]:
    q = (
        select(Claim)
        .options(joinedload(Claim.verification).joinedload(Verification.evidence), joinedload(Claim.outlet))
        .where(Claim.story_id == story_id)
        .order_by(Claim.id)
    )
    return list(session.scalars(q).unique())


def verdict_counts(
    session: Session, story_ids: list[int] | None = None, outlet_id: int | None = None
) -> dict:
    q = (
        select(Claim.story_id, Verification.verdict, func.count())
        .join(Verification, Verification.claim_id == Claim.id)
        .group_by(Claim.story_id, Verification.verdict)
    )
    if story_ids is not None:
        q = q.where(Claim.story_id.in_(story_ids or [-1]))
    if outlet_id is not None:
        q = q.where(Claim.outlet_id == outlet_id)
    out: dict = {}
    for sid, verdict, n in session.execute(q):
        key = sid if story_ids is not None else "total"
        out.setdefault(key, {}).setdefault(verdict, 0)
        out[key][verdict] += n
    return out


def latest_pieces(
    session: Session, *, kind: str | None = None, limit: int = 12, offset: int = 0
) -> list[Piece]:
    q = select(Piece).options(joinedload(Piece.topic)).where(Piece.status == "publicada")
    if kind:
        q = q.where(Piece.kind == kind)
    q = q.order_by(Piece.created_at.desc(), Piece.id.desc()).limit(limit).offset(offset)
    return list(session.scalars(q))


def topic_view(session: Session, topic_id: int) -> tuple[Topic | None, dict[str, Piece], list[Story]]:
    topic = session.get(Topic, topic_id)
    if topic is None:
        return None, {}, []
    pieces: dict[str, Piece] = {}
    for p in sorted(topic.pieces, key=lambda p: p.created_at):
        if p.status == "publicada":
            pieces[p.kind] = p  # la mas reciente de cada tipo
    stories = list(
        session.scalars(
            select(Story)
            .where(Story.topic_id == topic.id)
            .order_by(Story.n_outlets.desc(), Story.last_seen.desc())
        )
    )
    return topic, pieces, stories


def outlets_by_slug(session: Session, slugs: list[str]) -> dict[str, Outlet]:
    if not slugs:
        return {}
    return {o.slug: o for o in session.scalars(select(Outlet).where(Outlet.slug.in_(slugs)))}


def all_verifications(session: Session, limit: int = 200) -> list[Claim]:
    q = (
        select(Claim)
        .options(
            joinedload(Claim.verification).joinedload(Verification.evidence),
            joinedload(Claim.outlet),
            joinedload(Claim.article),
        )
        .order_by(Claim.id.desc())
        .limit(limit)
    )
    return list(session.scalars(q).unique())


def thread_for_story(session: Session, story_id: int) -> Thread | None:
    return session.scalars(
        select(Thread).where(Thread.anchor_story_id == story_id, Thread.status == "publicado")
    ).first()


def front_threads(session: Session, story_ids: list[int], limit: int = 3) -> list[Thread]:
    """Hilos publicados de las historias de cabecera, en el orden de la portada."""
    if not story_ids:
        return []
    by_story = {
        t.anchor_story_id: t
        for t in session.scalars(
            select(Thread).where(Thread.anchor_story_id.in_(story_ids), Thread.status == "publicado")
        )
    }
    return [by_story[s] for s in story_ids if s in by_story][:limit]


def outlet_profile(session: Session, outlet_id: int, recent: int = 8) -> dict:
    """Cifras del medio y sus ultimos cambios de titular o extracto detectados (ADR 0015)."""
    since = datetime.now(UTC) - timedelta(days=30)
    n_total = session.scalar(select(func.count(Article.id)).where(Article.outlet_id == outlet_id)) or 0
    n_30d = (
        session.scalar(
            select(func.count(Article.id)).where(
                Article.outlet_id == outlet_id, Article.published_at >= since
            )
        )
        or 0
    )
    n_rev = (
        session.scalar(select(func.count(ArticleRevision.id)).where(ArticleRevision.outlet_id == outlet_id))
        or 0
    )
    n_rev_articles = (
        session.scalar(
            select(func.count(func.distinct(ArticleRevision.article_id))).where(
                ArticleRevision.outlet_id == outlet_id
            )
        )
        or 0
    )
    changes = list(
        session.scalars(
            select(ArticleRevision)
            .options(joinedload(ArticleRevision.article))
            .where(ArticleRevision.outlet_id == outlet_id)
            .order_by(ArticleRevision.detected_at.desc(), ArticleRevision.id.desc())
            .limit(recent)
        )
    )
    return {
        "articles": n_total,
        "articles_30d": n_30d,
        "revisions": n_rev,
        "revised_articles": n_rev_articles,
        "changes": changes,
    }


def article_claims(session: Session, article_id: int) -> list[Claim]:
    return list(
        session.scalars(
            select(Claim)
            .options(joinedload(Claim.verification))
            .where(Claim.article_id == article_id)
            .order_by(Claim.id)
        )
    )
