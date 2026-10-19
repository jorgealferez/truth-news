"""Consultas de las paginas de entidades: ranking, ficha con linea temporal, medios, co-apariciones y
afirmaciones (ADR 0028). Las descubiertas solo se publican con >= 2 medios; las del registro, siempre."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from truthnews.analysis.ranking import BAD, Contradiction, contradictions
from truthnews.models import Article, Claim, Entity, Mention, Outlet, Verification, utcnow

MIN_OUTLETS_PUBLIC = 2
TIMELINE_MONTHS = 36
COMENTION_SAMPLE = 500


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def public(q):
    return q.where(or_(Entity.curated.is_(True), Entity.n_outlets >= MIN_OUTLETS_PUBLIC))


def ranking(
    session: Session, kind: str | None = None, days: int = 30, limit: int = 60, now: datetime | None = None
) -> list[tuple[Entity, int, int]]:
    """(entidad, noticias en el periodo, medios en el periodo), de mas a menos presente."""
    now = now or utcnow()
    q = public(
        select(
            Entity,
            func.count(Mention.id).label("n"),
            func.count(func.distinct(Mention.outlet_id)).label("o"),
        )
        .join(Mention, Mention.entity_id == Entity.id)
        .where(Mention.published_at >= now - timedelta(days=days))
        .group_by(Entity.id)
        .order_by(func.count(Mention.id).desc(), Entity.name)
        .limit(limit)
    )
    if kind:
        q = q.where(Entity.kind == kind)
    return [(e, n, o) for e, n, o in session.execute(q)]


def for_story(session: Session, story_id: int, limit: int = 10) -> list[tuple[Entity, int]]:
    """Quien aparece en una historia (sin lugares): entidad y en cuantas de sus noticias."""
    return list(
        session.execute(
            public(
                select(Entity, func.count(Mention.id))
                .join(Mention, Mention.entity_id == Entity.id)
                .where(Mention.story_id == story_id, Entity.kind != "lugar")
                .group_by(Entity.id)
                .order_by(func.count(Mention.id).desc(), Entity.name)
                .limit(limit)
            )
        )
    )


@dataclass
class Profile:
    entity: Entity
    months: list[tuple[str, int, int]] = field(default_factory=list)  # (AAAA-MM, rastreadas, archivo)
    outlets: list[tuple[Outlet, int]] = field(default_factory=list)
    together: list[tuple[Entity, int]] = field(default_factory=list)
    quotes: list[Mention] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    contradictions: list[Contradiction] = field(default_factory=list)
    latest: list[Article] = field(default_factory=list)
    checked: int = 0
    bad: int = 0
    archive_articles: int = 0

    @property
    def peak(self) -> int:
        return max((r + a for _, r, a in self.months), default=0)


def profile(session: Session, entity_id: int, now: datetime | None = None) -> Profile | None:
    now = now or utcnow()
    ent = session.get(Entity, entity_id)
    if ent is None or not (ent.curated or ent.n_outlets >= MIN_OUTLETS_PUBLIC):
        return None
    p = Profile(ent)
    since = (now - timedelta(days=31 * TIMELINE_MONTHS)).replace(day=1)
    by_month: dict[str, Counter] = {}
    for published, origin in session.execute(
        select(Mention.published_at, Article.origin)
        .join(Article, Article.id == Mention.article_id)
        .where(Mention.entity_id == ent.id, Mention.published_at >= since)
    ):
        by_month.setdefault(f"{_aware(published):%Y-%m}", Counter())[origin] += 1
        p.archive_articles += origin == "archivo"
    p.months = [(m, c["rss"], c["archivo"]) for m, c in sorted(by_month.items())]
    p.outlets = list(
        session.execute(
            select(Outlet, func.count(Mention.id))
            .join(Mention, Mention.outlet_id == Outlet.id)
            .where(Mention.entity_id == ent.id)
            .group_by(Outlet.id)
            .order_by(func.count(Mention.id).desc(), Outlet.name)
            .limit(12)
        )
    )
    recent_articles = (
        select(Mention.article_id)
        .where(Mention.entity_id == ent.id)
        .order_by(Mention.published_at.desc())
        .limit(COMENTION_SAMPLE)
        .scalar_subquery()
    )
    p.together = list(
        session.execute(
            public(
                select(Entity, func.count(Mention.id))
                .join(Mention, Mention.entity_id == Entity.id)
                .where(Mention.article_id.in_(recent_articles), Entity.id != ent.id, Entity.kind != "lugar")
                .group_by(Entity.id)
                .order_by(func.count(Mention.id).desc(), Entity.name)
                .limit(12)
            )
        )
    )
    p.quotes = list(
        session.scalars(
            select(Mention)
            .options(joinedload(Mention.article).joinedload(Article.outlet))
            .where(Mention.entity_id == ent.id, Mention.role == "dice")
            .order_by(Mention.published_at.desc())
            .limit(10)
        )
    )
    p.claims = list(
        session.scalars(
            select(Claim)
            .options(
                joinedload(Claim.verification).joinedload(Verification.evidence),
                joinedload(Claim.outlet),
                joinedload(Claim.article),
            )
            .where(Claim.speaker_entity_id == ent.id)
            .order_by(Claim.created_at.desc())
            .limit(30)
        ).unique()
    )
    judged = [c for c in p.claims if c.verification and c.verification.verdict != "sin-datos"]
    p.checked, p.bad = len(judged), sum(c.verification.verdict in BAD for c in judged)
    p.contradictions = [c for c in contradictions(session, now=now) if c.entity_id == ent.id]
    p.latest = list(
        session.scalars(
            select(Article)
            .options(joinedload(Article.outlet))
            .join(Mention, Mention.article_id == Article.id)
            .where(Mention.entity_id == ent.id)
            .order_by(Article.published_at.desc())
            .limit(20)
        )
    )
    return p


def oldest_article(session: Session, entity_id: int) -> datetime | None:
    first = session.scalar(select(func.min(Mention.published_at)).where(Mention.entity_id == entity_id))
    return _aware(first) if first else None
