"""Puntuacion de contraste por historia y orden de portada (ADR 0012).

Lo que tiene algo que marcar va primero: cifras en disputa entre medios, afirmaciones contrastadas con
datos oficiales (mas peso si no cuadran), omisiones y lenguaje cargado. El numero de medios y la
tendencia solo desempatan: entre historias sin nada que marcar nunca suman 1 punto, que es lo minimo
que aporta una diferencia real.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from truthnews.analysis.compare import Comparison, compare
from truthnews.models import Article, Claim, Story, Verification, utcnow

VERDICT_WEIGHT = {"falso": 3.0, "enganoso": 3.0, "impreciso": 2.0, "verdadero": 1.0, "sin-datos": 0.0}
TREND_HOURS = 6
BACKFILL_DAYS = 7


def contrast_of(comp: Comparison, verdicts: dict[str, int]) -> tuple[float, dict]:
    """(puntuacion, resumen publico) de una historia a partir de su comparacion y sus veredictos."""
    disputes = sorted({k.split(" ·")[0] for k in comp.disputes})  # "detenidos ·2": otro hecho, mismo rotulo
    checked = {k: n for k, n in verdicts.items() if k != "sin-datos" and n}
    score = (
        2.0 * min(len(comp.disputes), 3)
        + min(sum(VERDICT_WEIGHT[k] * n for k, n in checked.items()), 9.0)
        + 1.0 * min(len(comp.omissions), 3)
        + 0.5 * min(len(comp.loaded), 4)
    )
    summary = {
        "disputas": disputes,
        "veredictos": checked,
        "omisiones": len(comp.omissions),
        "lenguaje_cargado": len(comp.loaded),
        "base": comp.basis,
    }
    return round(score, 2), summary


def priority_of(score: float, n_outlets: int, outlets_recent: int) -> float:
    return round(score + 0.05 * min(n_outlets, 10) + 0.1 * min(outlets_recent, 4), 3)


def score_stories(session: Session, since: datetime, now: datetime | None = None) -> dict:
    """Puntua las historias multimedio tocadas desde `since` y las de 7 dias aun sin puntuar."""
    now = now or utcnow()
    touched_by_claims = select(Claim.story_id).join(Verification).where(Verification.checked_at >= since)
    stories = list(
        session.scalars(
            select(Story).where(
                Story.n_outlets >= 2,
                or_(
                    Story.updated_at >= since,
                    Story.id.in_(touched_by_claims),
                    (Story.contrast.is_(None) & (Story.last_seen >= now - timedelta(days=BACKFILL_DAYS))),
                ),
            )
        )
    )
    ids = [s.id for s in stories]
    if not ids:
        return {"scored": 0, "with_contrast": 0}
    verdicts: dict[int, Counter] = {}
    for sid, verdict, n in session.execute(
        select(Claim.story_id, Verification.verdict, func.count())
        .join(Verification, Verification.claim_id == Claim.id)
        .where(Claim.story_id.in_(ids))
        .group_by(Claim.story_id, Verification.verdict)
    ):
        verdicts.setdefault(sid, Counter())[verdict] += n
    recent = dict(
        session.execute(
            select(Article.story_id, func.count(func.distinct(Article.outlet_id)))
            .where(Article.story_id.in_(ids), Article.published_at >= now - timedelta(hours=TREND_HOURS))
            .group_by(Article.story_id)
        ).all()
    )
    arts: dict[int, list[Article]] = {}
    for a in session.scalars(
        select(Article).options(joinedload(Article.outlet)).where(Article.story_id.in_(ids))
    ):
        arts.setdefault(a.story_id, []).append(a)
    with_contrast = 0
    for st in stories:
        score, summary = contrast_of(compare(arts.get(st.id, [])), dict(verdicts.get(st.id, {})))
        st.contrast_score, st.contrast = score, summary
        st.priority = priority_of(score, st.n_outlets, recent.get(st.id, 0))
        with_contrast += score > 0
    session.flush()
    return {"scored": len(stories), "with_contrast": with_contrast}
