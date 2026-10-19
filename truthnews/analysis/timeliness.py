"""Quien informa primero y bien (ADR 0041).

Solo en historias con dato oficial: las que tienen al menos una afirmacion comprobada (verdadero,
impreciso, falso o enganoso). Para cada medio de la historia se mide:

- **acierta**: cuanto tarda, desde el primer articulo de la historia, en publicar una afirmacion que
  coincide con el dato oficial (veredicto verdadero);
- **se adelanta mal**: si su primera afirmacion comprobada en la historia no cuadra con el dato.

Mismo metodo para todos y sin puntuacion unica: con menos de MIN_STORIES historias un medio no entra en la
tabla ordenada, como en la fiabilidad (ADR 0021).
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from statistics import median

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from truthnews.models import Article, Claim, Verification

MIN_STORIES = 5
RIGHT = "verdadero"
WRONG = ("impreciso", "falso", "enganoso")


@dataclass
class OutletInStory:
    outlet: str
    right_after_h: float | None  # horas desde el primer articulo hasta su primera cifra correcta
    first_wrong: bool  # su primera afirmacion comprobada no cuadra


@dataclass
class StoryTiming:
    story_id: int
    start: datetime
    outlets: list[OutletInStory]

    @property
    def first_right(self) -> OutletInStory | None:
        right = [o for o in self.outlets if o.right_after_h is not None]
        return min(right, key=lambda o: o.right_after_h) if right else None


def _naive(d: datetime) -> datetime:
    # Todo se guarda en UTC; SQLite pierde la zona al agregar.
    return d.replace(tzinfo=None) if d.tzinfo else d


def _hours(a: datetime, b: datetime) -> float:
    return round(max((_naive(b) - _naive(a)).total_seconds(), 0) / 3600, 1)


def timings(claims: list[Claim], starts: dict[int, datetime]) -> list[StoryTiming]:
    """`claims`: afirmaciones con verificacion y articulo; `starts`: primer articulo de cada historia."""
    by_story: dict[int, dict[str, list[Claim]]] = defaultdict(lambda: defaultdict(list))
    for c in claims:
        v = c.verification
        if c.story_id is None or v is None or (v.verdict != RIGHT and v.verdict not in WRONG):
            continue
        by_story[c.story_id][c.outlet.name].append(c)
    out = []
    for sid, per_outlet in by_story.items():
        # Si el agrupador movio todos los articulos de la historia a otra, la afirmacion conserva su
        # story_id y la historia no tiene primer articulo: se toma el primero de sus afirmaciones.
        start = starts.get(sid) or min(c.article.published_at for cs in per_outlet.values() for c in cs)
        rows = []
        for name, cs in sorted(per_outlet.items()):
            cs.sort(key=lambda c: (c.article.published_at, c.id))
            right = [c for c in cs if c.verification.verdict == RIGHT]
            rows.append(
                OutletInStory(
                    name,
                    _hours(start, right[0].article.published_at) if right else None,
                    cs[0].verification.verdict in WRONG,
                )
            )
        out.append(StoryTiming(sid, start, rows))
    return sorted(out, key=lambda t: t.story_id)


@dataclass
class OutletTiming:
    outlet: str
    stories: int = 0
    right: int = 0
    first_wrong: int = 0
    delays: list[float] = field(default_factory=list)

    @property
    def ranked(self) -> bool:
        return self.stories >= MIN_STORIES

    @property
    def median_h(self) -> float | None:
        return round(median(self.delays), 1) if self.delays else None


def by_outlet(story_timings: list[StoryTiming]) -> tuple[list[OutletTiming], list[OutletTiming]]:
    """(medios con muestra suficiente, medios con pocas historias), cada uno ordenado."""
    acc: dict[str, OutletTiming] = {}
    for st in story_timings:
        for o in st.outlets:
            rec = acc.setdefault(o.outlet, OutletTiming(o.outlet))
            rec.stories += 1
            rec.first_wrong += o.first_wrong
            if o.right_after_h is not None:
                rec.right += 1
                rec.delays.append(o.right_after_h)
    recs = list(acc.values())
    ranked = sorted(
        (r for r in recs if r.ranked),
        key=lambda r: (-r.right / r.stories, r.median_h if r.median_h is not None else 1e9, r.outlet.lower()),
    )
    few = sorted((r for r in recs if not r.ranked), key=lambda r: (-r.stories, r.outlet.lower()))
    return ranked, few


def load(session: Session, story_id: int | None = None) -> list[StoryTiming]:
    q = (
        select(Claim)
        .join(Verification, Verification.claim_id == Claim.id)
        .options(joinedload(Claim.verification), joinedload(Claim.outlet), joinedload(Claim.article))
        .where(Claim.story_id.is_not(None))
    )
    if story_id is not None:
        q = q.where(Claim.story_id == story_id)
    claims = list(session.scalars(q).unique())
    ids = {c.story_id for c in claims}
    starts = dict(
        session.execute(
            select(Article.story_id, func.min(Article.published_at))
            .where(Article.story_id.in_(ids or [-1]))
            .group_by(Article.story_id)
        ).all()
    )
    return timings(claims, starts)
