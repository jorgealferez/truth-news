"""Declaraciones de los partidos juzgadas con el juez de siempre y guardadas aparte (ADR 0030).

Lee `political_statement` (carril Global, ADR 0024), busca afirmaciones comprobables con
`analysis.judge.judge_text` (reglas + `verify.py`, carril Verificaciones) y guarda cada una con su
veredicto y su evidencia en `statement_check`. No toca `claim`: una declaracion no es una noticia de un
medio. El mismo mensaje publicado en varios canales del mismo partido en pocas horas se juzga una vez, y
cuando cambia el metodo (`METHOD_VERSION`) se vuelve a juzgar dejando escrita la correccion.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews import registry
from truthnews.analysis.claims import ClaimCandidate
from truthnews.analysis.judge import judge_candidate, judge_text
from truthnews.analysis.verify import METHOD_VERSION, Result, Verifier
from truthnews.classify import normalize
from truthnews.models import Entity, PoliticalStatement, StatementCheck

WINDOW_DAYS = 30
DUPLICATE_HOURS = 6
# Las reglas son de castellano: una declaracion en euskera, gallego o catalan rara vez da candidatos, y si
# no los da no se juzga (no se dice nada de ella). Sin columna de idioma en political_statement (ADR 0024).
LANGUAGE = "es"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def actor_entities(session: Session, actors: list[registry.ActorSpec] | None = None) -> dict[str, Entity]:
    """Slug del partido en el registro politico -> su entidad `partido` (nombre, nombre completo o alias)."""
    index: dict[str, Entity] = {}
    for ent in session.scalars(select(Entity).where(Entity.kind == "partido")):
        for name in [ent.name, *(ent.aliases or [])]:
            index.setdefault(normalize(name), ent)
    out: dict[str, Entity] = {}
    for actor in actors if actors is not None else registry.load_political():
        for name in (actor.name, actor.full_name, actor.slug):
            ent = index.get(normalize(name))
            if ent is not None:
                out[actor.slug] = ent
                break
    return out


def _evidence(result: Result) -> list[dict]:
    return [
        {"source": o.source, "label": o.label, "url": o.url, "period": o.period, "value": o.value}
        for o in result.observations
    ]


def _apply(check: StatementCheck, result: Result) -> None:
    check.verdict = result.verdict
    check.confidence = result.confidence
    check.explanation = result.explanation
    check.method = result.method
    check.evidence = _evidence(result)
    check.checked_at = datetime.now(UTC)


def rejudge_outdated(session: Session, verifier: Verifier | None = None) -> dict:
    """Vuelve a juzgar las afirmaciones juzgadas con un metodo anterior; si el veredicto cambia, lo dice."""
    stale = list(
        session.scalars(select(StatementCheck).where(~StatementCheck.method.endswith(f"/{METHOD_VERSION}")))
    )
    changed = 0
    for check in stale:
        before = check.verdict
        cand = ClaimCandidate(
            check.text, check.indicator, check.geo, check.value, check.unit, check.direction, check.period
        )
        result = judge_candidate(cand, verifier)
        _apply(check, result)
        if result.verdict != before:
            changed += 1
            check.explanation = f"{result.explanation} (Corregido: antes «{before}», con un metodo anterior.)"
    return {"rejudged": len(stale), "changed": changed}


def run(
    session: Session,
    verifier: Verifier | None = None,
    now: datetime | None = None,
    actors: list[registry.ActorSpec] | None = None,
) -> dict:
    """Juzga las declaraciones de los ultimos WINDOW_DAYS dias aun sin sus afirmaciones guardadas."""
    now = now or datetime.now(UTC)
    verifier = verifier or Verifier()
    stats = {"statements": 0, "duplicates": 0, "claims": 0, **rejudge_outdated(session, verifier)}
    entities = actor_entities(session, actors)
    done = set(session.scalars(select(StatementCheck.statement_id).distinct()))
    last_seen: dict[tuple[str, str], datetime] = {}
    rows = session.scalars(
        select(PoliticalStatement)
        .where(PoliticalStatement.published_at >= now - timedelta(days=WINDOW_DAYS))
        .order_by(PoliticalStatement.published_at, PoliticalStatement.id)
    )
    for st in rows:
        body = (st.summary or st.text or "").strip()
        published = _aware(st.published_at)
        key = (st.actor, normalize(body))
        prev = last_seen.get(key)
        last_seen[key] = published
        if prev is not None and published - prev <= timedelta(hours=DUPLICATE_HOURS):
            stats["duplicates"] += 1  # el mismo mensaje en otro canal del mismo partido
            continue
        if st.id in done or not body:
            continue
        stats["statements"] += 1
        speaker = entities.get(st.actor)
        seen: set[tuple] = set()
        for cand, result in judge_text(body, LANGUAGE, st.country or "XX", published, verifier):
            uniq = (cand.indicator, cand.geo, cand.value)
            if uniq in seen:
                continue
            seen.add(uniq)
            check = StatementCheck(
                statement_id=st.id,
                speaker_entity_id=speaker.id if speaker else None,
                text=cand.text,
                indicator=cand.indicator,
                geo=cand.geo,
                value=cand.value,
                unit=cand.unit,
                direction=cand.direction,
                period=cand.period,
                extractor="reglas",
            )
            _apply(check, result)
            session.add(check)
            stats["claims"] += 1
    session.flush()
    return stats


def without_channel(actors: list[registry.ActorSpec] | None = None, country: str = "ES") -> list[str]:
    """Partidos del registro sin canal oficial verificado: sus declaraciones no se pueden juzgar todavia."""
    specs = actors if actors is not None else registry.load_political()
    return sorted(a.name for a in specs if a.country == country and not a.channels)
