"""Que se publica: lo mas contrastado, mediatico o verificado, nunca en revision ni sin fuente.

- Historias con contraste (cifras en disputa, veredictos, omisiones; `story.priority`, ADR 0012) que
  cuentan al menos dos medios con enlace a su noticia.
- Hilos publicados (nunca en `revision` ni `error`) con fuentes citadas.
- Verificaciones con veredicto falso, enganoso o impreciso y evidencia oficial con enlace.

Los titulares con lenguaje cargado (`analysis.compare.LOADED`) no se publican: el tono de nuestras
redes es neutral aunque el medio no lo sea.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from truthnews import registry
from truthnews.analysis.compare import compare, loaded_words
from truthnews.models import Article, Claim, Story, Thread, Verification, utcnow
from truthnews.social.compose import Draft, clip, fmt
from truthnews.web import seo

PUBLISHABLE_VERDICTS = {"falso": 6.0, "enganoso": 6.0, "impreciso": 4.0}
THREAD_SCORE = 4.0


@dataclass
class Candidate:
    kind: str  # historia | hilo | verificacion
    ref_id: int
    score: float
    draft: Draft
    image_story_id: int | None
    language: str = "es"
    date: datetime | None = None  # para ordenar en el RSS


def _verdict_line(verdicts: dict[str, int], lang: str) -> str:
    checked = {k: n for k, n in verdicts.items() if k != "sin-datos" and n}
    if not checked:
        return ""
    parts = ", ".join(f"{registry.t(lang, 'verdict_' + k).lower()}: {n}" for k, n in sorted(checked.items()))
    return f"Contrastado con datos oficiales: {sum(checked.values())} afirmaciones ({parts})."


def stories(session: Session, site_url: str, since: datetime, min_score: float, lang: str) -> list[Candidate]:
    rows = list(
        session.scalars(
            select(Story).where(
                Story.n_outlets >= 2, Story.contrast_score >= min_score, Story.last_seen >= since
            )
        )
    )
    if not rows:
        return []
    ids = [s.id for s in rows]
    arts: dict[int, list[Article]] = {}
    for a in session.scalars(
        select(Article).options(joinedload(Article.outlet)).where(Article.story_id.in_(ids))
    ):
        arts.setdefault(a.story_id, []).append(a)
    verdicts: dict[int, dict[str, int]] = {}
    for sid, verdict in session.execute(
        select(Claim.story_id, Verification.verdict)
        .join(Verification, Verification.claim_id == Claim.id)
        .where(Claim.story_id.in_(ids))
    ):
        verdicts.setdefault(sid, {}).setdefault(verdict, 0)
        verdicts[sid][verdict] += 1
    out = []
    for st in rows:
        sourced = [a for a in arts.get(st.id, []) if a.url]
        if len({a.outlet_id for a in sourced}) < 2 or loaded_words(st.title, lang):
            continue
        comp = compare(sourced)
        lines = [
            f"{d.noun.capitalize()}: de {fmt(d.low)} a {fmt(d.high)} según el medio."
            for d in comp.dispute_summaries()[:2]
        ]
        lines += [_verdict_line(verdicts.get(st.id, {}), lang), f"Lo cuentan {st.n_outlets} medios."]
        draft = Draft(
            clip(st.title, 200),
            lines,
            "Cómo lo cuenta cada medio:",
            site_url + seo.path("historia", st.id, st.title),
        )
        out.append(
            Candidate("historia", st.id, st.priority or st.contrast_score, draft, st.id, lang, st.last_seen)
        )
    return out


def threads(session: Session, site_url: str, since: datetime, lang: str) -> list[Candidate]:
    out = []
    for th in session.scalars(select(Thread).where(Thread.status == "publicado", Thread.updated_at >= since)):
        c = th.content or {}
        if not th.sources or loaded_words(th.title, lang):
            continue
        lines = [clip(c.get("resumen") or "", 400), clip(c.get("por_que_ahora") or "", 300)]
        draft = Draft(
            f"Hilo: {clip(th.title, 200)}",
            lines,
            "Cronología y fuentes:",
            site_url + seo.path("hilo", th.id, th.title),
        )
        score = THREAD_SCORE + 0.1 * min(len(th.sources), 10)
        out.append(
            Candidate("hilo", th.id, score, draft, th.anchor_story_id, th.language or lang, th.updated_at)
        )
    return out


def verifications(session: Session, site_url: str, since: datetime, lang: str) -> list[Candidate]:
    q = (
        select(Verification)
        .options(
            joinedload(Verification.evidence),
            joinedload(Verification.claim).joinedload(Claim.outlet),
            joinedload(Verification.claim).joinedload(Claim.article),
        )
        .where(Verification.verdict.in_(PUBLISHABLE_VERDICTS), Verification.checked_at >= since)
    )
    out = []
    for v in session.scalars(q).unique():
        claim = v.claim
        evidence = [e for e in v.evidence if e.url]
        if not evidence or not claim.article or not claim.article.url:
            continue
        ev = evidence[0]
        period = f" ({ev.period})" if ev.period else ""
        lines = [
            f"{claim.outlet.name}: «{clip(claim.text, 180)}»",
            clip(v.explanation, 300),
            f"Fuente: {clip(ev.label, 120)}{period}.",
        ]
        url = (
            site_url + seo.path("historia", claim.story_id, session.get(Story, claim.story_id).title)
            if claim.story_id
            else site_url + seo.path("noticia", claim.article_id, claim.article.title)
        )
        verdict = registry.t(lang, "verdict_" + v.verdict)
        draft = Draft(f"Verificación: {verdict}", lines, "Datos y enlaces:", url)
        out.append(
            Candidate(
                "verificacion",
                v.id,
                PUBLISHABLE_VERDICTS[v.verdict],
                draft,
                claim.story_id,
                lang,
                v.checked_at,
            )
        )
    return out


def candidates(
    session: Session,
    site_url: str,
    min_score: float = 2.0,
    window_hours: int = 72,
    lang: str = "es",
    now: datetime | None = None,
) -> list[Candidate]:
    """Todo lo publicable en la ventana, de mas a menos relevante."""
    since = (now or utcnow()) - timedelta(hours=window_hours)
    site_url = site_url.rstrip("/")
    found = (
        stories(session, site_url, since, min_score, lang)
        + threads(session, site_url, since, lang)
        + verifications(session, site_url, since, lang)
    )
    return sorted(found, key=lambda c: (-c.score, c.kind, c.ref_id))
