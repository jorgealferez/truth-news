"""Equilibrio en lo que publicamos (ADR 0043): a quien afecta cada pieza y si un actor acapara lo negativo.

Actor de una pieza:
- verificacion: quien dijo la frase si se conoce (`claim.speaker`, ADR 0028); si no, los partidos que
  menciona la noticia de la que sale;
- historia e hilo: los partidos mencionados en la historia (`mention` de entidades `partido`).

Nunca se etiqueta un "bando": no lo podemos medir (esencia: sin bandos). Una pieza es negativa si lleva
un veredicto falso o enganoso. Un actor se marca cuando en 24 h supera `THRESHOLD` de las piezas negativas
publicadas (con al menos `MIN_NEGATIVE`) **y** ese peso excede en `MARGIN` su peso entre todos los
veredictos negativos del mismo periodo: si los datos lo justifican (es quien mas afirmaciones falsas
acumula), no se toca. Marcar solo reordena: sus piezas negativas pasan detras de las de relevancia
parecida; ninguna se descarta y ningun veredicto se oculta en la web.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews.models import (
    SOCIAL_NETWORKS,
    Claim,
    Entity,
    Mention,
    SocialPost,
    Story,
    Thread,
    Verification,
    utcnow,
)

NEGATIVE = ("falso", "enganoso")
THRESHOLD = 0.6
MIN_NEGATIVE = 3
MARGIN = 0.15
HOURS = 24


def _parties(session: Session, *, story_id: int | None = None, article_id: int | None = None) -> set[str]:
    q = select(Entity.name).join(Mention, Mention.entity_id == Entity.id).where(Entity.kind == "partido")
    if story_id is not None:
        q = q.where(Mention.story_id == story_id)
    elif article_id is not None:
        q = q.where(Mention.article_id == article_id)
    else:
        return set()
    return set(session.scalars(q.distinct()))


def verification_actors(session: Session, v: Verification) -> set[str]:
    claim = v.claim
    if claim.speaker is not None:
        return {claim.speaker.name}
    return _parties(session, article_id=claim.article_id)


def piece(session: Session, kind: str, ref_id: int) -> tuple[set[str], bool]:
    """(actores, negativa) de una pieza."""
    if kind == "verificacion":
        v = session.get(Verification, ref_id)
        if v is None:
            return set(), False
        return verification_actors(session, v), v.verdict in NEGATIVE
    if kind == "hilo":
        th = session.get(Thread, ref_id)
        return (_parties(session, story_id=th.anchor_story_id) if th and th.anchor_story_id else set()), False
    if session.get(Story, ref_id) is None:
        return set(), False
    negative = session.scalar(
        select(Verification.id)
        .join(Claim, Claim.id == Verification.claim_id)
        .where(Claim.story_id == ref_id, Verification.verdict.in_(NEGATIVE))
        .limit(1)
    )
    return _parties(session, story_id=ref_id), negative is not None


def _shares(counts: Counter, total: int) -> dict[str, float]:
    return {a: round(n / total, 3) for a, n in counts.most_common()} if total else {}


def measure(session: Session, now: datetime | None = None, hours: int = HOURS) -> dict:
    """Medida de las ultimas `hours`: piezas en espanol (una por contenido, sin contar cada red) y el
    reparto por actor de las negativas, frente al de todos los veredictos negativos del periodo."""
    since = (now or utcnow()) - timedelta(hours=hours)
    keys = set(
        session.execute(
            select(SocialPost.kind, SocialPost.ref_id).where(
                SocialPost.created_at >= since, SocialPost.network.in_(SOCIAL_NETWORKS)
            )
        ).all()
    )
    published: Counter = Counter()
    negative = 0
    for kind, ref_id in keys:
        actors, neg = piece(session, kind, ref_id)
        if neg:
            negative += 1
            published.update(actors)
    pool: Counter = Counter()
    pool_total = 0
    for v in session.scalars(
        select(Verification).where(Verification.checked_at >= since, Verification.verdict.in_(NEGATIVE))
    ):
        pool_total += 1
        pool.update(verification_actors(session, v))
    pub_share, pool_share = _shares(published, negative), _shares(pool, pool_total)
    flagged = sorted(
        a
        for a, share in pub_share.items()
        if negative >= MIN_NEGATIVE and share > THRESHOLD and share > pool_share.get(a, 0.0) + MARGIN
    )
    return {
        "horas": hours,
        "piezas": len(keys),
        "negativas": negative,
        "por_actor": pub_share,
        "veredictos_negativos": pool_total,
        "por_actor_en_los_datos": pool_share,
        "marcados": flagged,
    }


def diversify(session: Session, candidates: list, flagged: list[str]) -> list:
    """Las piezas negativas de un actor marcado pasan detras de las demas; el orden relativo se mantiene
    y ninguna se descarta (saldran cuando haya cupo)."""
    if not flagged:
        return candidates
    marked = set(flagged)
    front, back = [], []
    for c in candidates:
        actors, negative = piece(session, c.kind, c.ref_id)
        (back if negative and actors & marked else front).append(c)
    return front + back
