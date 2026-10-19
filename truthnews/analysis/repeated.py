"""Afirmaciones que se repiten (como Full Fact; ADR 0035): la misma cifra sobre el mismo indicador en varios
articulos, medios y dias, con su veredicto cuando lo hay.

Dos afirmaciones son "la misma" si coinciden indicador, territorio, unidad, periodo citado, valor
redondeado a una decima y hablante o fuente citada (si la hay). Solo se agrupan afirmaciones extraidas por
el codigo o la IA y ya guardadas (`claim`); el veredicto lo decide la verificacion de cada una (ADR 0007),
aqui solo se agrupa y se cuenta.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from truthnews.models import Article, Claim, Verification

MIN_ARTICLES = 2
CHECKED = ("verdadero", "impreciso", "falso", "enganoso")


def key_of(c: Claim) -> tuple:
    # Con el hablante o la fuente citada: la cifra de un ministro y la de una ONG no son la misma afirmacion.
    return (c.indicator, c.geo, c.unit, c.period or "", round(c.value, 1), c.speaker_entity_id)


def slug_of(key: tuple) -> str:
    indicator, geo, unit, period, value, speaker = key
    parts = (indicator, geo, period or "sp", f"{value:g}", unit, f"h{speaker}" if speaker else "")
    return "-".join(str(x) for x in parts if x).replace(".", "_")


@dataclass
class Repeated:
    key: tuple
    claims: list[Claim] = field(default_factory=list)

    @property
    def slug(self) -> str:
        return slug_of(self.key)

    @property
    def outlets(self) -> list[str]:
        out: list[str] = []
        for c in sorted(self.claims, key=lambda c: c.article.published_at):
            if c.outlet.name not in out:
                out.append(c.outlet.name)
        return out

    @property
    def first(self) -> datetime:
        return min(c.article.published_at for c in self.claims)

    @property
    def last(self) -> datetime:
        return max(c.article.published_at for c in self.claims)

    @property
    def days(self) -> int:
        return len({c.article.published_at.date() for c in self.claims})

    @property
    def verdict(self) -> str | None:
        """El veredicto mas reciente con dato; None si ninguna esta comprobada."""
        checked = [
            c.verification for c in self.claims if c.verification and c.verification.verdict in CHECKED
        ]
        return max(checked, key=lambda v: v.checked_at).verdict if checked else None

    @property
    def evidence(self):
        for c in self.claims:
            if c.verification and c.verification.evidence:
                return c.verification.evidence[0]
        return None

    @property
    def example(self) -> Claim:
        return min(self.claims, key=lambda c: c.article.published_at)


def group(claims: list[Claim]) -> list[Repeated]:
    """Grupos con la misma afirmacion en al menos MIN_ARTICLES articulos, los mas repetidos primero."""
    by_key: dict[tuple, Repeated] = {}
    for c in claims:
        by_key.setdefault(key_of(c), Repeated(key_of(c))).claims.append(c)
    out = [r for r in by_key.values() if len({c.article_id for c in r.claims}) >= MIN_ARTICLES]
    return sorted(out, key=lambda r: (-len(r.outlets), -len(r.claims), r.slug))


def _claims(session: Session, *where) -> list[Claim]:
    q = (
        select(Claim)
        .options(
            joinedload(Claim.verification).joinedload(Verification.evidence),
            joinedload(Claim.outlet),
            joinedload(Claim.speaker),
            joinedload(Claim.article).joinedload(Article.outlet),
        )
        .where(*where)
    )
    return list(session.scalars(q).unique())


def repeated(session: Session) -> list[Repeated]:
    return group(_claims(session))


def repeated_for_story(session: Session, story_id: int) -> list[Repeated]:
    """Las afirmaciones de la historia que tambien aparecen en otros articulos."""
    keys = {key_of(c) for c in _claims(session, Claim.story_id == story_id)}
    if not keys:
        return []
    indicators = {k[0] for k in keys}
    return [r for r in group(_claims(session, Claim.indicator.in_(indicators))) if r.key in keys]
