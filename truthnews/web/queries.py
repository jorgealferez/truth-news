"""Consultas de lectura de la web: listados indexados por fecha con filtros de segmento."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import Session, joinedload

from truthnews.models import (
    Article,
    ArticleRevision,
    ArticleTranslation,
    Claim,
    CrawlRun,
    Outlet,
    Piece,
    Story,
    Thread,
    Topic,
    Verification,
)
from truthnews.web.citations import is_live

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


def breaking(session: Session, country: str, *, hours: int = 6, limit: int = 6) -> list[dict]:
    """Ultimo minuto: historias multimedio nacidas en las ultimas horas, la que mas se mueve primero.

    Cada entrada lleva cuantos medios se han sumado en la ultima hora ("impulso") y su hilo del porque,
    si existe: la franja recalca lo nuevo sin perder la comparativa (peticion del usuario 2026-10-19)."""
    now = datetime.now(UTC)
    since = now - timedelta(hours=hours)
    q = (
        select(Story)
        .where(
            Story.country == country,
            Story.n_outlets >= 2,
            Story.last_seen >= since,  # recorre ix_story_country_last_seen
            Story.first_seen >= since,
        )
        .order_by(Story.last_seen.desc(), Story.id.desc())
        .limit(limit)
    )
    stories = list(session.scalars(q))
    if not stories:
        return []
    ids = [s.id for s in stories]
    hour_ago = now - timedelta(hours=1)
    momentum = dict(
        session.execute(
            select(Article.story_id, func.count(func.distinct(Article.outlet_id)))
            .where(Article.story_id.in_(ids), Article.fetched_at >= hour_ago)
            .group_by(Article.story_id)
        ).all()
    )
    threads = {
        t.anchor_story_id: t
        for t in session.scalars(
            select(Thread).where(Thread.anchor_story_id.in_(ids), Thread.status == "publicado")
        )
    }
    return [{"story": s, "new_outlets": momentum.get(s.id, 0), "thread": threads.get(s.id)} for s in stories]


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
    q = (
        select(Piece)
        .options(joinedload(Piece.topic), joinedload(Piece.thread))
        .where(Piece.status == "publicada")
    )
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


def topic_titles(session: Session) -> dict[int, str]:
    """Titular publicado vigente de cada tema (el de su ultimo analisis): da el slug de su URL."""
    rows = session.execute(
        select(Piece.topic_id, Piece.title)
        .where(Piece.kind == "analisis", Piece.status == "publicada", Piece.topic_id.is_not(None))
        .order_by(Piece.created_at)
    )
    return dict(rows.all())


def topic_articles(session: Session, topic_id: int) -> list[Article]:
    return list(
        session.scalars(
            select(Article)
            .options(joinedload(Article.outlet))
            .join(Story, Story.id == Article.story_id)
            .where(Story.topic_id == topic_id)
            .order_by(Article.published_at)
        )
    )


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


def latest_checks(session: Session, limit: int = 8) -> list[Claim]:
    """Ultimas afirmaciones juzgadas con datos (sin las 'sin datos'): lo verificado, para portada."""
    q = (
        select(Claim)
        .join(Verification, Verification.claim_id == Claim.id)
        .options(joinedload(Claim.verification), joinedload(Claim.outlet))
        .where(Verification.verdict != "sin-datos")
        .order_by(Verification.checked_at.desc(), Claim.id.desc())
        .limit(limit)
    )
    return list(session.scalars(q).unique())


def thread_for_story(session: Session, story_id: int) -> Thread | None:
    return session.scalars(
        select(Thread).where(Thread.anchor_story_id == story_id, Thread.status == "publicado")
    ).first()


def story_title_translations(session: Session, story_ids: list[int], lang: str) -> dict[int, str]:
    """Titular traducido de cada historia: el de su articulo cabecera (mismo titular), ADR 0017."""
    if not story_ids:
        return {}
    q = (
        select(Story.id, ArticleTranslation.title)
        .join(Article, and_(Article.story_id == Story.id, Article.title == Story.title))
        .join(ArticleTranslation, ArticleTranslation.article_id == Article.id)
        .where(Story.id.in_(story_ids), ArticleTranslation.lang == lang, Article.language != lang)
    )
    return dict(session.execute(q).all())


def thread_piece(session: Session, thread_id: int) -> Piece | None:
    """Pieza propia publicada mas reciente de un hilo (ADR 0020)."""
    return session.scalars(
        select(Piece)
        .where(Piece.thread_id == thread_id, Piece.status == "publicada")
        .order_by(Piece.created_at.desc(), Piece.id.desc())
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
    # Cambios de los ultimos 30 dias, separando los directos (rotan el titular y no son rectificaciones).
    revs = list(
        session.scalars(
            select(ArticleRevision)
            .options(joinedload(ArticleRevision.article))
            .where(ArticleRevision.outlet_id == outlet_id, ArticleRevision.detected_at >= since)
            .order_by(ArticleRevision.detected_at.desc(), ArticleRevision.id.desc())
        )
    )
    live_ids = {r.article_id for r in revs if is_live(r.before, r.after, r.article.title)}
    edits = [r for r in revs if r.article_id not in live_ids]
    return {
        "articles": n_total,
        "articles_30d": n_30d,
        "revisions": len(edits),
        "revised_articles": len({r.article_id for r in edits}),
        "live_revisions": len(revs) - len(edits),
        "live_articles": len(live_ids),
        "changes": edits[:recent],
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
