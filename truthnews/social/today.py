"""Hoy en 1 minuto (ADR 0047): las claves del dia, solo con lo que ya esta contrastado en la base.

Cada clave lleva una frase, la cifra que circula, la oficial si la hay, el veredicto, la fuente y el
enlace. La frase de una verificacion es `web.verdicts.sentence`, que se arma solo con los datos guardados
(quien lo dice, lo que dice, el dato oficial, su periodo y su fuente): no hay texto libre ni IA, asi que
no puede aparecer una cifra o un juicio que no este en la base. Si no hay nada contrastado, la lista sale
vacia y la pagina lo dice: no se rellena.

Orden: primero lo falso y enganoso, despues lo impreciso y lo verdadero, y al final las cifras en disputa
entre medios (sin dato oficial, se dice asi). Un indicador o una historia aparecen una sola vez.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from truthnews.analysis.compare import compare
from truthnews.models import Claim, Story, Verification, utcnow
from truthnews.social.compose import fmt
from truthnews.web import queries, seo
from truthnews.web import verdicts as vview

LIMIT = 5
HOURS = 24
NO_OFFICIAL = "sin dato oficial con que contrastarlo."
ORDER = {"falso": 0, "enganoso": 0, "impreciso": 1, "verdadero": 2}


@dataclass
class Key:
    kind: str  # verificacion | disputa
    ref_id: int
    sentence: str
    verdict: str | None  # None en las disputas: no hay dato oficial con que juzgar
    said: str  # la cifra que circula
    official: str | None  # la cifra oficial, si la hay
    period: str | None
    source: str  # fuente oficial, o los medios en una disputa
    source_url: str | None
    path: str  # enlace interno a la verificacion o a la historia
    when: datetime


def _verifications(session: Session, since: datetime, lang: str) -> list[Key]:
    q = (
        select(Claim)
        .join(Verification, Verification.claim_id == Claim.id)
        .options(
            joinedload(Claim.verification).joinedload(Verification.evidence),
            joinedload(Claim.outlet),
            joinedload(Claim.article),
        )
        .where(Verification.checked_at >= since, Verification.verdict.in_(ORDER))
    )
    claims = sorted(
        session.scalars(q).unique(),
        key=lambda c: (ORDER[c.verification.verdict], -c.verification.checked_at.timestamp()),
    )
    out, seen = [], set()
    for c in claims:
        ev = [e for e in c.verification.evidence if e.value is not None and e.url]
        if not ev or c.indicator in seen:
            continue
        seen.add(c.indicator)
        off = ev[0]
        out.append(
            Key(
                kind="verificacion",
                ref_id=c.id,
                sentence=vview.sentence(c, lang),
                verdict=c.verification.verdict,
                said=vview.dato(c.value, c.unit, lang),
                official=vview.dato(off.value, c.unit, lang),
                period=off.period,
                source=vview.source_name(off.source, lang),
                source_url=off.url,
                path=f"/verificacion/{c.id}",
                when=c.verification.checked_at,
            )
        )
    return out


def _disputes(session: Session, since: datetime, lang: str) -> list[Key]:
    stories = session.scalars(
        select(Story)
        .where(Story.n_outlets >= 2, Story.last_seen >= since, Story.contrast_score > 0)
        .order_by(Story.priority.desc())
        .limit(30)
    )
    out = []
    for st in stories:
        if not (st.contrast or {}).get("disputas"):
            continue
        arts = [a for a in queries.story_articles(session, st.id) if a.url]
        summaries = compare(arts).dispute_summaries()
        if not summaries:
            continue
        d = summaries[0]
        low, high = fmt(d.low), fmt(d.high)
        out.append(
            Key(
                kind="disputa",
                ref_id=st.id,
                sentence=f"{st.title}: {d.noun}, de {low} a {high} según el medio; {NO_OFFICIAL}",
                verdict=None,
                said=f"{low} – {high}",
                official=None,
                period=None,
                source=f"{d.n_outlets} medios",
                source_url=None,
                path=seo.path("historia", st.id, st.title),
                when=st.last_seen,
            )
        )
    return out


def keys(
    session: Session, now: datetime | None = None, lang: str = "es", limit: int = LIMIT, hours: int = HOURS
) -> list[Key]:
    """Hasta `limit` claves de las ultimas `hours`; vacio si no hay nada contrastado."""
    since = (now or utcnow()) - timedelta(hours=hours)
    return (_verifications(session, since, lang) + _disputes(session, since, lang))[:limit]
