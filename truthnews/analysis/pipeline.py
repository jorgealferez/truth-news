"""Analisis de cada ciclo: historias (agrupacion entre medios) y afirmaciones verificadas."""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from truthnews.analysis.claims import ClaimCandidate, check_proposal, extract, indicators, world_countries
from truthnews.analysis.cluster import (
    DEFAULT_THRESHOLD,
    Doc,
    cluster,
    cosine,
    idf_table,
    representative,
    vectorize,
)
from truthnews.analysis.score import score_stories
from truthnews.analysis.verify import METHOD_VERSION, Result, Verifier
from truthnews.classify import normalize
from truthnews.models import Article, Claim, Evidence, Story, Verification, utcnow

log = logging.getLogger(__name__)
WINDOW = timedelta(hours=72)
# Relanzamiento (ADR 0012): una historia antigua con contraste vuelve si varios medios la retoman o si
# llegan datos nuevos que la contrastan.
RELAUNCH_LOOKBACK = timedelta(days=14)
RELAUNCH_MIN_SCORE = 2.0
RELAUNCH_THRESHOLD = 0.45  # coseno entre titulares; mas estricto que el de agrupacion (0,30)
RELAUNCH_AGE = timedelta(hours=48)
SERIES_POINTS = 14


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def assign_stories(session: Session, now: datetime | None = None, window: timedelta = WINDOW) -> dict:
    """Reagrupa los articulos de la ventana y conserva la identidad de las historias existentes."""
    now = now or utcnow()
    arts = list(
        session.scalars(
            select(Article).options(joinedload(Article.outlet)).where(Article.published_at >= now - window)
        )
    )
    docs = [
        Doc(
            key=a.id,
            title=a.title,
            summary=a.summary or "",
            published_at=_aware(a.published_at),
            outlet=a.outlet.slug,
        )
        for a in arts
    ]
    by_id = {a.id: a for a in arts}
    idf = idf_table(docs)
    older = [
        (st, vectorize(Doc(key=st.id, title=st.title), idf))
        for st in session.scalars(
            select(Story).where(
                Story.last_seen >= now - RELAUNCH_LOOKBACK,
                Story.last_seen < now - window,
                Story.contrast_score >= RELAUNCH_MIN_SCORE,
            )
        )
    ]
    created = updated = relaunched = 0
    used: set[int] = set()
    for group in cluster(docs, threshold=DEFAULT_THRESHOLD, idf=idf):
        members = [by_id[d.key] for d in group.members]
        lead = by_id[representative(group).key]
        # La historia conserva el id que tenga la mayoria de sus articulos (y que no se haya usado ya).
        votes = Counter(a.story_id for a in members if a.story_id and a.story_id not in used)
        story = session.get(Story, votes.most_common(1)[0][0]) if votes else None
        if story is None and len({a.outlet_id for a in members}) >= 2 and older:
            vec = vectorize(Doc(key=lead.id, title=lead.title), idf)
            sim, best = max(((cosine(vec, v), st) for st, v in older if st.id not in used), default=(0, None))
            if best is not None and sim >= RELAUNCH_THRESHOLD:
                story, best.relaunched_at = best, now
                relaunched += 1
        if story is None:
            story = Story(
                title=members[0].title,
                category=members[0].category,
                country=members[0].country,
                first_seen=members[0].published_at,
                last_seen=members[0].published_at,
            )
            session.add(story)
            session.flush()
            created += 1
        else:
            updated += 1
        used.add(story.id)
        story.title = lead.title
        story.category = (
            Counter(a.category for a in members if a.category != "opinion").most_common(1)[0][0]
            if any(a.category != "opinion" for a in members)
            else lead.category
        )
        story.country = Counter(a.country for a in members).most_common(1)[0][0]
        story.updated_at = now
        for a in members:
            a.story_id = story.id
    session.flush()
    # Recuento desde la base: una historia relanzada o de larga vida conserva sus articulos antiguos.
    for sid, n_arts, n_outlets, first, last in session.execute(
        select(
            Article.story_id,
            func.count(Article.id),
            func.count(func.distinct(Article.outlet_id)),
            func.min(Article.published_at),
            func.max(Article.published_at),
        )
        .where(Article.story_id.in_(used or {-1}))
        .group_by(Article.story_id)
    ):
        st = session.get(Story, sid)
        st.n_articles, st.n_outlets, st.first_seen, st.last_seen = n_arts, n_outlets, first, last
    session.flush()
    return {
        "articles": len(arts),
        "stories_created": created,
        "stories_updated": updated,
        "stories_relaunched": relaunched,
    }


def _store(ver: Verification, result: Result) -> None:
    if result.verdict != "sin-datos" and not result.observations:
        raise AssertionError("C6: un veredicto sin evidencia no se publica")
    ver.verdict, ver.confidence = result.verdict, result.confidence
    ver.explanation, ver.method, ver.checked_at = result.explanation, result.method, utcnow()
    ver.evidence.clear()
    for obs in result.observations:
        ver.evidence.append(
            Evidence(
                source=obs.source,
                label=obs.label,
                url=obs.url,
                period=obs.period,
                value=obs.value,
                retrieved_at=obs.retrieved_at,
                # Ultimos periodos de la serie: el grafico de la verificacion los pinta con la cifra.
                payload={**obs.extra, "serie": dict(sorted(obs.history.items())[-SERIES_POINTS:])},
            )
        )


def save_claim(
    session: Session, a: Article, cand: ClaimCandidate, verifier: Verifier, extractor: str = "reglas"
) -> str | None:
    """Guarda y juzga una afirmacion nueva del articulo; None si ya estaba (misma cifra e indicador)."""
    exists = session.scalars(
        select(Claim).where(
            Claim.article_id == a.id, Claim.indicator == cand.indicator, Claim.value == cand.value
        )
    ).first()
    if exists:
        return None
    claim = Claim(
        article_id=a.id,
        story_id=a.story_id,
        outlet_id=a.outlet_id,
        text=cand.text,
        indicator=cand.indicator,
        geo=cand.geo,
        value=cand.value,
        unit=cand.unit,
        direction=cand.direction,
        extractor=extractor,
        period=cand.period,
    )
    session.add(claim)
    session.flush()
    result = verifier.judge(cand)
    ver = Verification(claim_id=claim.id)
    _store(ver, result)
    session.add(ver)
    # Datos nuevos sobre una historia antigua: vuelve a portada (ADR 0012).
    story = session.get(Story, a.story_id) if a.story_id else None
    if (
        story is not None
        and result.verdict != "sin-datos"
        and _aware(story.first_seen) < utcnow() - RELAUNCH_AGE
    ):
        story.relaunched_at = utcnow()
    return result.verdict


def default_geo_of(a: Article) -> str:
    """Pais que se supone cuando la frase no nombra ninguno: el del medio, salvo en una noticia de otro pais.

    Caso real (ABC, 19/10/2026, Internacional sobre Pakistan): "En septiembre, la inflacion se situo en el
    10,3 % interanual" se atribuia a Espana. Una noticia de Internacional, o que nombra otro pais en el
    titular o la entradilla, exige que la frase diga el territorio ("XX": sin pais por defecto).
    """
    if a.category == "internacional":
        return "XX"
    head = normalize(f"{a.title}. {a.summary or ''}")
    for iso, names in {**world_countries(), **indicators()["geo_names"]}.items():
        if iso in (a.country, "EU", "EA"):
            continue
        if any(re.search(r"(?<!\w)" + re.escape(normalize(n)) + r"(?!\w)", head) for n in names):
            return "XX"
    return a.country


def article_text(a: Article) -> str:
    return f"{a.title}. {a.summary or ''}\n{a.content_text or ''}"


def verify_claims(session: Session, since: datetime, verifier: Verifier | None = None) -> dict:
    """Extrae y verifica afirmaciones de los articulos ingeridos desde `since`."""
    verifier = verifier or Verifier()
    # Lo importado del archivo no se juzga con el dato de hoy (ADR 0028).
    arts = list(
        session.scalars(select(Article).where(Article.fetched_at >= since, Article.origin == "rss"))
    )
    n_claims = 0
    verdicts: Counter = Counter()
    for a in arts:
        pub = _aware(a.published_at)
        for cand in extract(article_text(a), a.language, default_geo_of(a), pub.year, pub.month):
            verdict = save_claim(session, a, cand, verifier)
            if verdict is None:
                continue
            n_claims += 1
            verdicts[verdict] += 1
    session.flush()
    return {"claims": n_claims, "verdicts": dict(verdicts)}


def reverify_outdated(session: Session, verifier: Verifier | None = None) -> dict:
    """Vuelve a juzgar los veredictos de una version anterior del metodo (ADR 0004/0006/0009).

    La afirmacion se vuelve a extraer con las reglas vigentes: si ya no es atribuible, se retira (veredicto
    `sin-datos`) con nota publica; si lo es, se juzga con el territorio y el periodo vigentes.
    """
    verifier = verifier or Verifier()
    changed: Counter = Counter()
    stale = session.scalars(
        select(Verification)
        .options(joinedload(Verification.claim).joinedload(Claim.article))
        .where(~Verification.method.endswith(f"/{METHOD_VERSION}"))
    ).unique()
    for ver in stale:
        c = ver.claim
        a = c.article
        pub = _aware(a.published_at)
        before = ver.verdict
        if c.extractor == "ia":
            # Sin volver a llamar a la IA: los campos guardados pasan otra vez por las reglas vigentes.
            k = check_proposal(
                c.text,
                article_text(a),
                c.indicator,
                c.geo,
                c.value,
                c.period,
                c.direction,
                default_geo_of(a),
                pub.year,
                pub.month,
            )
            current = [k] if isinstance(k, ClaimCandidate) else []
        else:
            current = [
                k
                for k in extract(c.text, a.language, default_geo_of(a), pub.year, pub.month)
                if k.indicator == c.indicator and k.value == c.value
            ]
        if not current:
            _store(
                ver,
                Result(
                    "sin-datos",
                    0.0,
                    "Afirmación retirada: con las reglas vigentes no se puede "
                    "atribuir con seguridad a un territorio o periodo con datos oficiales.",
                    f"retirada/{METHOD_VERSION}",
                ),
            )
        else:
            c.geo, c.period = current[0].geo, current[0].period
            _store(ver, verifier.judge(current[0]))
        if before != ver.verdict:
            # Transparencia: la correccion queda escrita en el propio veredicto publicado.
            ver.explanation += (
                f" [Corregido el {utcnow():%d/%m/%Y}: el veredicto anterior era «{before}» "
                "por un error de nuestro método, ya subsanado.]"
            )
        changed[f"{before}->{ver.verdict}"] += 1
    session.flush()
    return dict(changed)


def run(session: Session, since: datetime, verifier: Verifier | None = None) -> dict:
    verifier = verifier or Verifier()
    out = assign_stories(session)
    out.update(verify_claims(session, since, verifier))
    out["reverified"] = reverify_outdated(session, verifier)
    out["scores"] = score_stories(session, since)
    log.info("analisis: %s", out)
    return out
