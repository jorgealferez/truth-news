"""Foco (ADR 0056): interruptor para un suceso grave que hay que analizar a fondo ya.

Con `AI_FOCUS` puesto (terminos separados por comas), lo que case con ellos pasa primero por cada paso de IA
(piezas, hilos, afirmaciones e investigacion), con su propia bolsa de gasto y una cadencia mas corta, sin
competir por el cupo general. Sin `AI_FOCUS` no cambia nada. Se quita borrando la variable.
"""

from __future__ import annotations

from datetime import UTC, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews.classify import _contains, normalize
from truthnews.models import Article, Investigation, Story, Topic, utcnow
from truthnews.web import queries


class Focus:
    def __init__(self, terms: tuple[str, ...] | list[str] = ()):
        self.terms = tuple(t for t in (normalize(x.strip()) for x in terms) if t)

    def __bool__(self) -> bool:
        return bool(self.terms)

    def matches(self, *texts: str | None) -> bool:
        """Algun termino aparece como palabra o expresion entera (sin tildes ni mayusculas)."""
        blob = normalize(" ".join(t for t in texts if t))
        return any(_contains(blob, t) for t in self.terms)

    def article(self, a: Article) -> bool:
        return self.matches(a.title, a.summary)

    def story(self, session: Session, st: Story) -> bool:
        if self.matches(st.title):
            return True
        titles = session.scalars(select(Article.title).where(Article.story_id == st.id).limit(50))
        return any(self.matches(t) for t in titles)

    def stories(self, session: Session, country: str, hours: int = 72, limit: int = 10) -> list[Story]:
        """Historias multimedio del foco, en el orden de la portada."""
        if not self:
            return []
        pool = queries.top_stories(session, country=country, hours=hours, limit=200)
        return [st for st in pool if self.story(session, st)][:limit]

    def topics(self, session: Session, country: str, hours: int = 72, limit: int = 10) -> list[Topic]:
        """Temas del foco: su titulo o el de alguna de sus historias casa."""
        if not self:
            return []
        since = utcnow() - timedelta(hours=hours)
        rows = session.scalars(
            select(Topic)
            .where(Topic.country == country, Topic.last_seen >= since)
            .order_by(Topic.n_outlets.desc(), Topic.last_seen.desc())
            .limit(200)
        )
        out = [t for t in rows if self.matches(t.title) or any(self.story(session, s) for s in t.stories)]
        return out[:limit]


def ensure_investigation(session: Session, question: str, country: str, refresh: timedelta) -> str:
    """La investigacion del foco existe y se rehace cada `refresh` mientras el suceso evoluciona."""
    question = question.strip()
    if not 10 <= len(question) <= 500:
        return "sin pregunta"
    inv = session.scalars(
        select(Investigation).where(Investigation.question == question).order_by(Investigation.id.desc())
    ).first()
    if inv is None:
        session.add(Investigation(question=question, country=country))
        session.flush()
        return "creada"
    updated = inv.updated_at if inv.updated_at.tzinfo else inv.updated_at.replace(tzinfo=UTC)
    if inv.status in ("publicada", "error") and updated <= utcnow() - refresh:
        inv.status = "pendiente"
        session.flush()
        return "reabierta"
    return inv.status
