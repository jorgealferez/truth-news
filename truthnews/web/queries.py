"""Consultas de lectura de la web: listados indexados por fecha con filtros de segmento."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from truthnews.models import Article, CrawlRun, Outlet

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
        "articles": session.scalar(select(func.count(Article.id))) or 0,
        "outlets": session.scalar(select(func.count(Outlet.id)).where(Outlet.active.is_(True))) or 0,
        "last_crawl": last.finished_at if last else None,
    }
