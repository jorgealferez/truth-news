"""Lo que la pagina de una eleccion ensena: fechas oficiales, partidos por igual y cobertura (ADR 0036).

Mismo formato y mismo orden (alfabetico por slug) para todos los partidos; un partido sin canal o sin
programa localizado aparece igual, con el hueco dicho. Nada se califica: se cita.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from truthnews.classify import normalize
from truthnews.elections.calendar import Election, _aliases
from truthnews.models import VERDICTS, PoliticalStatement, StatementCheck, Story
from truthnews.registry import load_political

STATEMENTS_PER_PARTY = 3
COVERAGE = 12
_STORY_WORDS = ("%elecci%", "%comicios%", "%campaña%", "%candidat%", "%electoral%", "%encuesta%", "%sondeo%")


def _since(e: Election) -> datetime:
    return datetime.combine(e.opens(), datetime.min.time(), UTC)


def _regional(e: Election, text: str) -> bool:
    """Para una eleccion de un territorio, el texto tiene que nombrarlo (por sus alias del registro)."""
    if not e.region:
        return True
    t = normalize(text)
    return any(re.search(rf"\b{re.escape(n)}\b", t) for n in _aliases().get(e.region, ()))


def key_dates(e: Election, today: date) -> list[dict]:
    rows = []
    if e.convened:
        rows.append({"key": "el_convened", "date": e.convened})
    if e.campaign:
        rows.append({"key": "el_campaign_start", "date": e.campaign[0]})
        rows.append({"key": "el_campaign_end", "date": e.campaign[1]})
    rows.append({"key": "el_poll", "date": e.date})
    if e.constitution:
        rows.append({"key": "el_constitution", "date": e.constitution})
    for r in rows:
        r["past"] = r["date"] < today
    return rows


def parties(session: Session, e: Election) -> list[dict]:
    """Por partido: declaraciones de sus canales oficiales en la ventana, su juicio y su programa."""
    actors = [a for a in load_political() if a.country == e.country]
    if not actors:
        return []
    since = _since(e)
    slugs = [a.slug for a in actors]
    rows = session.scalars(
        select(PoliticalStatement)
        .where(
            PoliticalStatement.country == e.country,
            PoliticalStatement.actor.in_(slugs),
            PoliticalStatement.published_at >= since,
        )
        .order_by(PoliticalStatement.published_at.desc())
        .limit(2000)
    ).all()
    by_actor: dict[str, list[PoliticalStatement]] = {}
    for s in rows:
        if _regional(e, f"{s.text} {s.summary or ''}"):
            by_actor.setdefault(s.actor, []).append(s)
    verdicts: dict[str, dict[str, int]] = {}
    for actor, verdict, n in session.execute(
        select(PoliticalStatement.actor, StatementCheck.verdict, func.count())
        .join(StatementCheck, StatementCheck.statement_id == PoliticalStatement.id)
        .where(PoliticalStatement.actor.in_(slugs), PoliticalStatement.published_at >= since)
        .group_by(PoliticalStatement.actor, StatementCheck.verdict)
    ):
        verdicts.setdefault(actor, {})[verdict] = n
    out = []
    for a in actors:
        said = by_actor.get(a.slug, [])
        out.append(
            {
                "actor": a,
                "n_statements": len(said),
                "statements": said[:STATEMENTS_PER_PARTY],
                "channels": len(a.channels),
                "verdicts": [(v, verdicts.get(a.slug, {}).get(v, 0)) for v in VERDICTS],
                "n_checked": sum(verdicts.get(a.slug, {}).values()),
                "program": e.programs.get(a.slug),
            }
        )
    return out


def coverage(session: Session, e: Election, now: datetime) -> list[Story]:
    """Historias del pais desde que se abrio la ventana que hablan de elecciones o campana."""
    rows = session.scalars(
        select(Story)
        .where(
            Story.country == e.country,
            Story.last_seen >= _since(e),
            Story.last_seen <= now + timedelta(days=1),
            or_(*(Story.title.ilike(w) for w in _STORY_WORDS)),
        )
        .order_by(Story.priority.desc(), Story.last_seen.desc())
        .limit(COVERAGE * 4)
    ).all()
    return [s for s in rows if _regional(e, s.title)][:COVERAGE]


def page(session: Session, e: Election, now: datetime) -> dict:
    today = now.date()
    return {
        "e": e,
        "phase": e.phase(today),
        "days_left": e.days_left(today),
        "dates": key_dates(e, today),
        "parties": parties(session, e),
        "stories": coverage(session, e, now),
    }
