"""Declaraciones de los partidos juzgadas con el juez de siempre y guardadas aparte (ADR 0031).

Lee `political_statement` (carril Global, ADR 0024), busca afirmaciones comprobables con
`analysis.judge.judge_text` (reglas + `verify.py`, carril Verificaciones) y guarda cada una con su
veredicto y su evidencia en `statement_check`. No toca `claim`: una declaracion no es una noticia de un
medio. El mismo mensaje publicado en varios canales del mismo partido en pocas horas se juzga una vez, y
cuando cambia el metodo (`METHOD_VERSION`) se vuelve a juzgar dejando escrita la correccion.

Con IA (`run_ai`), las frases con cifra que las reglas no recogen se proponen a `ai.claims.propose` (la misma
validacion por codigo que en las noticias) con un tope de llamadas por ciclo. Para no repetir lo ya enviado
sin necesidad de tabla, el ultimo id de declaracion enviado se guarda en `CrawlRun.stats` (AI_CURSOR).
Cuando una declaracion ya enviada recibe despues el cuerpo de su comunicado (ADR 0051), se vuelve a
enviar una vez: la fecha del ultimo cuerpo enviado va en AI_BODY_CURSOR.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import chain

from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews import registry
from truthnews.ai import claims as ai_claims
from truthnews.ai.client import AIClient
from truthnews.analysis.claims import ClaimCandidate
from truthnews.analysis.judge import judge_candidate, judge_text
from truthnews.analysis.verify import METHOD_VERSION, Result, Verifier
from truthnews.classify import normalize
from truthnews.models import CrawlRun, Entity, PoliticalStatement, StatementCheck

WINDOW_DAYS = 30
DUPLICATE_HOURS = 6
# Las reglas son de castellano: una declaracion en euskera, gallego o catalan rara vez da candidatos, y si
# no los da no se juzga (no se dice nada de ella). Sin columna de idioma en political_statement (ADR 0024).
LANGUAGE = "es"
AI_CURSOR = "statement_ai_cursor"
AI_BODY_CURSOR = "statement_ai_body_cursor"
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


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
        body = _body(st)
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
            if _add(session, st, speaker, cand, result, "reglas", seen):
                stats["claims"] += 1
    session.flush()
    return stats


def _add(session, st, speaker, cand: ClaimCandidate, result: Result, extractor: str, seen: set) -> bool:
    """Guarda una afirmacion juzgada salvo que ya este (misma cifra del mismo indicador y territorio)."""
    uniq = (st.id, cand.indicator, cand.geo, cand.value)
    if uniq in seen:
        return False
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
        extractor=extractor,
    )
    _apply(check, result)
    session.add(check)
    return True


def _body(st: PoliticalStatement) -> str:
    """El comunicado entero si se descargo (titular y cuerpo, ADR 0051); si no, el extracto del canal."""
    if st.body:
        return f"{(st.text or '').strip().rstrip('.')}. {st.body.strip()}".lstrip(". ")
    return (st.summary or st.text or "").strip()


def _cursor(session: Session, key: str):
    for stats in session.scalars(select(CrawlRun.stats).order_by(CrawlRun.id.desc()).limit(50)):
        if stats and key in stats:
            return stats[key]
    return None


def ai_cursor(session: Session) -> int:
    """Ultimo id de declaracion ya enviado a la IA (0 si nunca)."""
    return int(_cursor(session, AI_CURSOR) or 0)


def ai_body_cursor(session: Session) -> datetime:
    """Fecha del ultimo cuerpo de comunicado ya enviado a la IA (EPOCH si nunca)."""
    value = _cursor(session, AI_BODY_CURSOR)
    return _aware(datetime.fromisoformat(value)) if value else EPOCH


def run_ai(
    session: Session,
    ai: AIClient,
    run_id: int | None,
    verifier: Verifier | None = None,
    max_calls: int = 2,
    now: datetime | None = None,
    actors: list[registry.ActorSpec] | None = None,
) -> dict:
    """Frases con cifra de declaraciones aun no enviadas, propuestas a la IA, validadas y juzgadas."""
    now = now or datetime.now(UTC)
    verifier = verifier or Verifier()
    cursor, body_cursor = ai_cursor(session), ai_body_cursor(session)
    window = PoliticalStatement.published_at >= now - timedelta(days=WINDOW_DAYS)
    new = session.scalars(
        select(PoliticalStatement)
        .where(PoliticalStatement.id > cursor, window)
        .order_by(PoliticalStatement.id)
    )
    # Ya enviadas sin cuerpo y que lo recibieron despues: se envian otra vez, por orden de descarga.
    late = session.scalars(
        select(PoliticalStatement)
        .where(
            PoliticalStatement.id <= cursor,
            PoliticalStatement.body_status == "ok",
            PoliticalStatement.body_fetched_at > body_cursor,
            window,
        )
        .order_by(PoliticalStatement.body_fetched_at, PoliticalStatement.id)
    )
    room = ai_claims.BATCH * max_calls
    items: list[ai_claims.Item] = []
    last, last_body, seen_text = cursor, body_cursor, set()
    for st in chain(new, late):
        body = _body(st)
        key = (st.actor, normalize(body))
        sentences = ai_claims.candidate_sentences(body) if key not in seen_text else []
        if len(items) + len(sentences) > room:
            if items:
                break  # la declaracion entera va en el siguiente ciclo
            sentences = sentences[:room]  # una sola declaracion mas larga que el tope no atasca el cursor
        seen_text.add(key)
        geo = st.country or "XX"
        items += [ai_claims.Item(s, body, geo, _aware(st.published_at), st) for s in sentences]
        if st.id > cursor:
            last = st.id
        else:
            last_body = _aware(st.body_fetched_at)
    accepted, stats = ai_claims.propose(ai, items, max_calls) if items else ([], {"frases_candidatas": 0})
    if items and not stats.get("llamadas"):
        return {**stats, "claims": 0}  # la IA no respondio: el cursor no avanza y se reintenta
    entities = actor_entities(session, actors)
    seen = set(
        session.execute(
            select(
                StatementCheck.statement_id,
                StatementCheck.indicator,
                StatementCheck.geo,
                StatementCheck.value,
            )
        )
    )
    claims = 0
    for it, cand in accepted:
        st = it.ref
        if _add(session, st, entities.get(st.actor), cand, judge_candidate(cand, verifier), "ia", seen):
            claims += 1
    row = session.get(CrawlRun, run_id) if run_id is not None else None
    if row is not None:
        row.stats = {**(row.stats or {}), AI_CURSOR: last, AI_BODY_CURSOR: last_body.isoformat()}
    session.flush()
    return {**stats, "claims": claims, "cursor": last}


def without_channel(actors: list[registry.ActorSpec] | None = None, country: str = "ES") -> list[str]:
    """Partidos del registro sin canal oficial verificado: sus declaraciones no se pueden juzgar todavia."""
    specs = actors if actors is not None else registry.load_political()
    return sorted(a.name for a in specs if a.country == country and not a.channels)
