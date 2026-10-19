"""Fiabilidad por medio: historial de veredictos, ranking por exactitud comprobada y puntos ciegos (ADR 0023).

Mismo metodo para todos los medios y sin etiquetas de ideologia. La exactitud es la proporcion de sus
afirmaciones comprobadas contra un dato oficial que resultan verdaderas; los veredictos "sin-datos" no
cuentan. Para ordenar se usa el limite inferior del intervalo de Wilson al 95 %: un medio con 2 aciertos
de 2 no puede pasar por delante de otro con 40 de 45. Con menos de MIN_CHECKS comprobaciones el medio no
entra en el ranking y se dice ("pocas verificaciones todavia").
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from truthnews.models import Article, Claim, Outlet, Story, Verification, utcnow

MIN_CHECKS = 5
CHECKED = ("verdadero", "impreciso", "falso", "enganoso")
BLIND_MIN_OUTLETS = 5  # una historia "grande": la cuentan al menos 5 medios del mismo pais
BLIND_DAYS = 7


def wilson_lower(k: int, n: int, z: float = 1.96) -> float:
    """Limite inferior del intervalo de Wilson para k aciertos de n."""
    if n == 0:
        return 0.0
    p = k / n
    centre = p + z * z / (2 * n)
    margin = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    return (centre - margin) / (1 + z * z / n)


@dataclass
class Record:
    outlet: Outlet
    counts: Counter = field(default_factory=Counter)  # veredicto -> afirmaciones

    @property
    def checked(self) -> int:
        return sum(self.counts[v] for v in CHECKED)

    @property
    def right(self) -> int:
        return self.counts["verdadero"]

    @property
    def accuracy(self) -> float | None:
        return self.right / self.checked if self.checked else None

    @property
    def lower(self) -> float:
        return wilson_lower(self.right, self.checked)

    @property
    def ranked(self) -> bool:
        return self.checked >= MIN_CHECKS

    def shares(self) -> list[tuple[str, int, int]]:
        """(veredicto, afirmaciones, % del total comprobado) para pintar el medidor."""
        n = self.checked or 1
        return [(v, self.counts[v], round(100 * self.counts[v] / n)) for v in CHECKED if self.counts[v]]


def records(session: Session, country: str | None = None, outlet_id: int | None = None) -> list[Record]:
    """Un registro por medio con al menos una afirmacion verificada."""
    q = (
        select(Outlet, Verification.verdict, func.count())
        .join(Claim, Claim.outlet_id == Outlet.id)
        .join(Verification, Verification.claim_id == Claim.id)
        .group_by(Outlet.id, Verification.verdict)
    )
    if country:
        q = q.where(Outlet.country == country)
    if outlet_id is not None:
        q = q.where(Outlet.id == outlet_id)
    out: dict[int, Record] = {}
    for outlet, verdict, n in session.execute(q):
        out.setdefault(outlet.id, Record(outlet)).counts[verdict] += n
    return list(out.values())


def ranking(recs: list[Record]) -> tuple[list[Record], list[Record]]:
    """(ranking con muestra suficiente, medios con pocas verificaciones), cada uno ordenado."""
    ranked = sorted(
        (r for r in recs if r.ranked), key=lambda r: (-r.lower, -r.checked, r.outlet.name.lower())
    )
    few = sorted(
        (r for r in recs if not r.ranked and r.checked),
        key=lambda r: (-r.checked, r.outlet.name.lower()),
    )
    return ranked, few


def history(session: Session, outlet_id: int, limit: int = 20) -> list[Claim]:
    """Las afirmaciones verificadas del medio, la mas reciente primero."""
    q = (
        select(Claim)
        .join(Verification, Verification.claim_id == Claim.id)
        .options(
            joinedload(Claim.verification).joinedload(Verification.evidence),
            joinedload(Claim.article),
        )
        .where(Claim.outlet_id == outlet_id)
        .order_by(Verification.checked_at.desc(), Claim.id.desc())
        .limit(limit)
    )
    return list(session.scalars(q).unique())


def missing_outlets(session: Session, story: Story, scope: str = "national") -> list[Outlet]:
    """Medios del pais de la historia que publicaron esos dias y no la cuentan ("quien no lo cuenta")."""
    since, until = story.first_seen - timedelta(hours=12), story.last_seen + timedelta(hours=12)
    covering = select(Article.outlet_id).where(Article.story_id == story.id)
    active = (
        select(Article.outlet_id)
        .where(Article.published_at >= since, Article.published_at <= until)
        .group_by(Article.outlet_id)
    )
    q = (
        select(Outlet)
        .where(
            Outlet.active.is_(True),
            Outlet.country == story.country,
            Outlet.scope == scope,
            Outlet.id.in_(active),
            Outlet.id.not_in(covering),
        )
        .order_by(Outlet.name)
    )
    return list(session.scalars(q))


@dataclass
class BlindSpots:
    big: int  # historias grandes de su pais mientras publicaba
    missed: list[Story]  # las que no conto, la mas cubierta primero

    @property
    def covered_share(self) -> int | None:
        return round(100 * (self.big - len(self.missed)) / self.big) if self.big else None


def blind_spots(
    session: Session, outlet: Outlet, now: datetime | None = None, days: int = BLIND_DAYS
) -> BlindSpots:
    """Historias grandes de su pais (>= BLIND_MIN_OUTLETS medios) de los ultimos dias que el medio no cuenta.

    Solo se cuentan las de los dias en que el medio publico algo: un medio parado no "omite".
    """
    now = now or utcnow()
    since = now - timedelta(days=days)
    days_active = {
        d.date() if isinstance(d, datetime) else d
        for (d,) in session.execute(
            select(Article.published_at).where(Article.outlet_id == outlet.id, Article.published_at >= since)
        )
    }
    if not days_active:
        return BlindSpots(0, [])
    big = [
        s
        for s in session.scalars(
            select(Story)
            .where(
                Story.country == outlet.country,
                Story.n_outlets >= BLIND_MIN_OUTLETS,
                Story.last_seen >= since,
            )
            .order_by(Story.n_outlets.desc(), Story.id)
        )
        if s.first_seen.date() in days_active or s.last_seen.date() in days_active
    ]
    covered = set(
        session.scalars(
            select(Article.story_id).where(
                Article.outlet_id == outlet.id, Article.story_id.in_([s.id for s in big] or [-1])
            )
        )
    )
    return BlindSpots(len(big), [s for s in big if s.id not in covered])
