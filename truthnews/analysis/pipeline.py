"""Analisis de cada ciclo: historias (agrupacion entre medios) y afirmaciones verificadas."""

from __future__ import annotations

import logging
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from truthnews.analysis.claims import extract
from truthnews.analysis.cluster import DEFAULT_THRESHOLD, Doc, cluster, representative
from truthnews.analysis.verify import Verifier
from truthnews.models import Article, Claim, Evidence, Story, Verification, utcnow

log = logging.getLogger(__name__)
WINDOW = timedelta(hours=72)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def assign_stories(session: Session, now: datetime | None = None, window: timedelta = WINDOW) -> dict:
    """Reagrupa los articulos de la ventana y conserva la identidad de las historias existentes."""
    now = now or utcnow()
    arts = list(
        session.scalars(
            select(Article).options(joinedload(Article.outlet)).where(Article.published_at >= now - window)
        )
    )
    docs = [
        Doc(
            key=a.id,
            title=a.title,
            summary=a.summary or "",
            published_at=_aware(a.published_at),
            outlet=a.outlet.slug,
        )
        for a in arts
    ]
    by_id = {a.id: a for a in arts}
    created = updated = 0
    used: set[int] = set()
    for group in cluster(docs, threshold=DEFAULT_THRESHOLD):
        members = [by_id[d.key] for d in group.members]
        # La historia conserva el id que tenga la mayoria de sus articulos (y que no se haya usado ya).
        votes = Counter(a.story_id for a in members if a.story_id and a.story_id not in used)
        story = session.get(Story, votes.most_common(1)[0][0]) if votes else None
        if story is None:
            story = Story(
                title=members[0].title,
                category=members[0].category,
                country=members[0].country,
                first_seen=members[0].published_at,
                last_seen=members[0].published_at,
            )
            session.add(story)
            session.flush()
            created += 1
        else:
            updated += 1
        used.add(story.id)
        outlets = {a.outlet_id for a in members}
        lead = by_id[representative(group).key]
        story.title = lead.title
        story.category = (
            Counter(a.category for a in members if a.category != "opinion").most_common(1)[0][0]
            if any(a.category != "opinion" for a in members)
            else lead.category
        )
        story.country = Counter(a.country for a in members).most_common(1)[0][0]
        story.first_seen = min(a.published_at for a in members)
        story.last_seen = max(a.published_at for a in members)
        story.n_articles = len(members)
        story.n_outlets = len(outlets)
        story.updated_at = now
        for a in members:
            a.story_id = story.id
    session.flush()
    return {"articles": len(arts), "stories_created": created, "stories_updated": updated}


def verify_claims(session: Session, since: datetime, verifier: Verifier | None = None) -> dict:
    """Extrae y verifica afirmaciones de los articulos ingeridos desde `since`."""
    verifier = verifier or Verifier()
    arts = list(session.scalars(select(Article).where(Article.fetched_at >= since)))
    n_claims = 0
    verdicts: Counter = Counter()
    for a in arts:
        text = f"{a.title}. {a.summary or ''}\n{a.content_text or ''}"
        for cand in extract(text, a.language, a.country, _aware(a.published_at).year):
            exists = session.scalars(
                select(Claim).where(
                    Claim.article_id == a.id, Claim.indicator == cand.indicator, Claim.value == cand.value
                )
            ).first()
            if exists:
                continue
            claim = Claim(
                article_id=a.id,
                story_id=a.story_id,
                outlet_id=a.outlet_id,
                text=cand.text,
                indicator=cand.indicator,
                geo=cand.geo,
                value=cand.value,
                unit=cand.unit,
                direction=cand.direction,
            )
            session.add(claim)
            session.flush()
            result = verifier.judge(cand)
            if result.verdict != "sin-datos" and not result.observations:
                raise AssertionError("C6: un veredicto sin evidencia no se publica")
            ver = Verification(
                claim_id=claim.id,
                verdict=result.verdict,
                confidence=result.confidence,
                explanation=result.explanation,
                method=result.method,
            )
            for obs in result.observations:
                ver.evidence.append(
                    Evidence(
                        source=obs.source,
                        label=obs.label,
                        url=obs.url,
                        period=obs.period,
                        value=obs.value,
                        retrieved_at=obs.retrieved_at,
                        payload=obs.extra,
                    )
                )
            session.add(ver)
            n_claims += 1
            verdicts[result.verdict] += 1
    session.flush()
    return {"claims": n_claims, "verdicts": dict(verdicts)}


def run(session: Session, since: datetime, verifier: Verifier | None = None) -> dict:
    out = assign_stories(session)
    out.update(verify_claims(session, since, verifier))
    log.info("analisis: %s", out)
    return out
