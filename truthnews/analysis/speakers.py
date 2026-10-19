"""Quien dice la verdad: historial de veredictos por partido y por persona (estilo PolitiFact, sin bandos).

Mismo metodo que la fiabilidad por medio (ADR 0023, `truthnews.analysis.reliability`): exactitud =
afirmaciones verdaderas sobre comprobadas, orden por el limite inferior de Wilson al 95 % y minimo de
MIN_CHECKS comprobaciones para entrar. Cuentan las afirmaciones que el texto atribuye a quien habla
(`claim.speaker_entity_id`, ADR 0028) y que el juez de siempre (`verify.py`) ha comprobado, mas las
afirmaciones de sus propias declaraciones en canales oficiales verificados (`statement_check`, ADR 0031).
No se deduce la afiliacion de nadie: un partido suma solo lo que se atribuye al partido.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from truthnews.analysis.reliability import Record
from truthnews.models import Claim, Entity, StatementCheck, Verification

KINDS = ("partido", "persona")


@dataclass
class SpeakerRecord(Record):
    """Un `Record` de fiabilidad cuyo sujeto es quien habla (en `outlet` no hay medio: es None)."""

    entity: Entity | None = None
    counts: Counter = field(default_factory=Counter)
    own: int = 0  # de ellas, las que salen de sus propias declaraciones (ADR 0031)


def records(session: Session, kind: str | None = None, entity_id: int | None = None) -> list[SpeakerRecord]:
    """Un registro por partido o persona con al menos una afirmacion suya verificada (noticias + canales)."""
    kinds = [kind] if kind else list(KINDS)
    news = (
        select(Entity, Verification.verdict, func.count())
        .join(Claim, Claim.speaker_entity_id == Entity.id)
        .join(Verification, Verification.claim_id == Claim.id)
        .where(Entity.kind.in_(kinds))
        .group_by(Entity.id, Verification.verdict)
    )
    own = (
        select(Entity, StatementCheck.verdict, func.count())
        .join(StatementCheck, StatementCheck.speaker_entity_id == Entity.id)
        .where(Entity.kind.in_(kinds))
        .group_by(Entity.id, StatementCheck.verdict)
    )
    if entity_id is not None:
        news, own = news.where(Entity.id == entity_id), own.where(Entity.id == entity_id)
    out: dict[int, SpeakerRecord] = {}
    for q, from_channel in ((news, False), (own, True)):
        for ent, verdict, n in session.execute(q):
            rec = out.setdefault(ent.id, SpeakerRecord(outlet=None, entity=ent))
            rec.counts[verdict] += n
            rec.own += n if from_channel else 0
    return list(out.values())


def ranking(recs: list[SpeakerRecord]) -> tuple[list[SpeakerRecord], list[SpeakerRecord]]:
    """(con muestra suficiente, con pocas comprobaciones), con el mismo orden que el ranking de medios."""
    ranked = sorted(
        (r for r in recs if r.ranked), key=lambda r: (-r.lower, -r.checked, r.entity.name.lower())
    )
    few = sorted(
        (r for r in recs if not r.ranked and r.checked), key=lambda r: (-r.checked, r.entity.name.lower())
    )
    return ranked, few


def history(session: Session, entity_id: int, limit: int = 20) -> list[Claim]:
    """Sus afirmaciones verificadas, la mas reciente primero, con el medio que las recoge."""
    return list(
        session.scalars(
            select(Claim)
            .join(Verification, Verification.claim_id == Claim.id)
            .options(joinedload(Claim.verification), joinedload(Claim.outlet), joinedload(Claim.article))
            .where(Claim.speaker_entity_id == entity_id)
            .order_by(Claim.created_at.desc())
            .limit(limit)
        ).unique()
    )
