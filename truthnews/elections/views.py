"""Lo que la pagina de una eleccion ensena: fechas oficiales, partidos por igual y cobertura (ADR 0036).

Mismo formato y mismo orden (alfabetico por slug) para todos los partidos; un partido sin canal o sin
programa localizado aparece igual, con el hueco dicho. Nada se califica: se cita.
"""

from __future__ import annotations

import re
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from truthnews.classify import normalize
from truthnews.elections import changes
from truthnews.elections.calendar import Election, _aliases, _world_names
from truthnews.models import VERDICTS, PoliticalStatement, Program, Promise, StatementCheck, Story
from truthnews.registry import load_political

HOME = "ES"  # pais por omision del sitio: su cobertura se busca por el pais de la historia
STATEMENTS_PER_PARTY = 3
PROMISES_PER_PARTY = 4
PROMISES_PAGE = 300
FIGURE_DAYS = 365
PCT_GAP = 0.5  # puntos: por debajo es redondeo
REL_GAP = 0.05
COVERAGE = 12
_STORY_WORDS = ("%elecci%", "%comicios%", "%campaña%", "%candidat%", "%electoral%", "%encuesta%", "%sondeo%")


def _since(e: Election) -> datetime:
    return datetime.combine(e.opens(), datetime.min.time(), UTC)


def _regional(e: Election, text: str) -> bool:
    """Para una eleccion de un territorio, el texto tiene que nombrarlo (por sus alias del registro)."""
    if not e.region:
        return True
    t = normalize(text)
    return any(re.search(rf"\b{re.escape(n)}\b", t) for n in _aliases().get(e.region, ()))


def key_dates(e: Election, today: date) -> list[dict]:
    rows = []
    if e.convened:
        rows.append({"key": "el_convened", "date": e.convened})
    if e.campaign:
        rows.append({"key": "el_campaign_start", "date": e.campaign[0]})
        rows.append({"key": "el_campaign_end", "date": e.campaign[1]})
    rows.append({"key": "el_poll", "date": e.date})
    if e.constitution:
        rows.append({"key": "el_constitution", "date": e.constitution})
    for r in rows:
        r["past"] = r["date"] < today
    return rows


def parties(session: Session, e: Election) -> list[dict]:
    """Por partido: declaraciones de sus canales oficiales en la ventana, su juicio y su programa."""
    actors = [a for a in load_political() if a.country == e.country]
    if not actors:
        return []
    since = _since(e)
    slugs = [a.slug for a in actors]
    rows = session.scalars(
        select(PoliticalStatement)
        .where(
            PoliticalStatement.country == e.country,
            PoliticalStatement.actor.in_(slugs),
            PoliticalStatement.published_at >= since,
        )
        .order_by(PoliticalStatement.published_at.desc())
        .limit(2000)
    ).all()
    by_actor: dict[str, list[PoliticalStatement]] = {}
    for s in rows:
        if _regional(e, f"{s.text} {s.summary or ''}"):
            by_actor.setdefault(s.actor, []).append(s)
    verdicts: dict[str, dict[str, int]] = {}
    for actor, verdict, n in session.execute(
        select(PoliticalStatement.actor, StatementCheck.verdict, func.count())
        .join(StatementCheck, StatementCheck.statement_id == PoliticalStatement.id)
        .where(PoliticalStatement.actor.in_(slugs), PoliticalStatement.published_at >= since)
        .group_by(PoliticalStatement.actor, StatementCheck.verdict)
    ):
        verdicts.setdefault(actor, {})[verdict] = n
    docs = programs_by_actor(session, e, slugs)
    changed = figure_changes(session, e, slugs, datetime.now(UTC))
    out = []
    for a in actors:
        said = by_actor.get(a.slug, [])
        current, previous = docs.get(a.slug, (None, None))
        out.append(
            {
                "actor": a,
                "n_statements": len(said),
                "statements": said[:STATEMENTS_PER_PARTY],
                "channels": len(a.channels),
                "verdicts": [(v, verdicts.get(a.slug, {}).get(v, 0)) for v in VERDICTS],
                "n_checked": sum(verdicts.get(a.slug, {}).values()),
                "program": e.programs.get(a.slug),
                "doc": current,
                "previous": previous,
                "promises": promises_for(session, e, a.slug, current, limit=PROMISES_PER_PARTY),
                "n_promises": count_promises(session, e, a.slug, current),
                "comparable": program_pair(session, e, a.slug) is not None,
                "figure_changes": changed.get(a.slug, []),
            }
        )
    return out


def programs_by_actor(session: Session, e: Election, slugs: list[str]) -> dict[str, tuple]:
    """Por partido: su programa para esta eleccion (si ya esta publicado) y el de la anterior del mismo tipo.

    Se prefiere el importado; si hay varios del mismo ano, el primero encontrado (el programa principal
    suele ir antes que sus resumenes en la pagina del partido).
    """
    rows = session.scalars(
        select(Program)
        .where(
            Program.country == e.country,
            Program.actor.in_(slugs),
            Program.election_kind == e.kind,
            Program.election_year <= e.date.year,
        )
        .order_by(Program.election_year.desc(), (Program.status == "importado").desc(), Program.id)
    ).all()
    out: dict[str, list] = {}
    for p in rows:
        cur, prev = out.setdefault(p.actor, [None, None])
        if p.election_year == e.date.year and cur is None:
            out[p.actor][0] = p
        elif p.election_year < e.date.year and prev is None:
            out[p.actor][1] = p
    return {k: (v[0], v[1]) for k, v in out.items()}


def _promise_query(e: Election, actor: str | None, doc: Program | None):
    """Promesas de esta eleccion: las de su programa y las dichas en canales oficiales en la ventana."""
    q = select(Promise).where(Promise.country == e.country)
    if actor:
        q = q.where(Promise.actor == actor)
    window = Promise.statement_id.is_not(None) & (Promise.made_at >= _since(e))
    in_program = (Promise.election_kind == e.kind) & (Promise.election_year == e.date.year)
    return q.where(window | (Promise.program_id.is_not(None) & in_program))


def promises_for(session: Session, e: Election, actor: str, doc, limit: int) -> list[Promise]:
    return list(session.scalars(_promise_query(e, actor, doc).order_by(Promise.made_at.desc()).limit(limit)))


def count_promises(session: Session, e: Election, actor: str, doc) -> int:
    return session.scalar(select(func.count()).select_from(_promise_query(e, actor, doc).subquery())) or 0


def promises_page(
    session: Session, e: Election, actor: str | None, topic: str | None, year: int | None
) -> dict:
    """Listado de promesas por partido y tema; `year` anterior = lo que se prometio en esa eleccion."""
    if year and year != e.date.year:
        q = select(Promise).where(
            Promise.country == e.country, Promise.election_kind == e.kind, Promise.election_year == year
        )
        if actor:
            q = q.where(Promise.actor == actor)
    else:
        q = _promise_query(e, actor, None)
    if topic:
        q = q.where(Promise.topic == topic)
    rows = list(
        session.scalars(q.order_by(Promise.actor, Promise.page, Promise.id).limit(PROMISES_PAGE))
    )
    by_topic: dict[str | None, int] = {}
    for p in rows:
        by_topic[p.topic] = by_topic.get(p.topic, 0) + 1
    return {"rows": rows, "by_topic": sorted(by_topic.items(), key=lambda kv: -kv[1]), "year": year}


def program_pair(session: Session, e: Election, actor: str) -> tuple[Program, Program] | None:
    """Los dos ultimos programas importados del partido para este tipo de eleccion (anterior, posterior)."""
    rows = session.scalars(
        select(Program)
        .where(
            Program.country == e.country,
            Program.actor == actor,
            Program.election_kind == e.kind,
            Program.election_year <= e.date.year,
            Program.status == "importado",
        )
        .order_by(Program.election_year.desc(), Program.id)
    ).all()
    latest: dict[int, Program] = {}
    for p in rows:
        latest.setdefault(p.election_year, p)
    years = sorted(latest, reverse=True)[:2]
    return (latest[years[1]], latest[years[0]]) if len(years) == 2 else None


def compare_programs(session: Session, e: Election, actor: str) -> dict | None:
    pair = program_pair(session, e, actor)
    if not pair:
        return None
    before, after = pair

    def of(p: Program) -> list[Promise]:
        return list(session.scalars(select(Promise).where(Promise.program_id == p.id).order_by(Promise.page)))

    return {"before": before, "after": after, "c": changes.compare(of(before), of(after))}


def figure_changes(session: Session, e: Election, slugs: list[str], now: datetime) -> dict[str, list]:
    """Por partido: mismo indicador, territorio y periodo con cifras distintas en declaraciones distintas.

    Solo con el periodo explicito e igual (un paro de 2024 y otro de 2025 no se contradicen) y con una
    diferencia que no sea redondeo; cada pareja cita las dos declaraciones con su fecha.
    """
    rows = session.execute(
        select(StatementCheck, PoliticalStatement)
        .join(PoliticalStatement, StatementCheck.statement_id == PoliticalStatement.id)
        .where(
            PoliticalStatement.country == e.country,
            PoliticalStatement.actor.in_(slugs),
            PoliticalStatement.published_at >= now - timedelta(days=FIGURE_DAYS),
            StatementCheck.period.is_not(None),
        )
        .order_by(PoliticalStatement.published_at)
    ).all()
    groups: dict[tuple, list] = {}
    for chk, st in rows:
        groups.setdefault((st.actor, chk.indicator, chk.geo, chk.period, chk.unit), []).append((chk, st))
    out: dict[str, list] = {}
    for (actor, *_), items in groups.items():
        first_chk, first_st = items[0]
        for chk, st in items[1:]:
            if st.id == first_st.id:
                continue
            gap = abs(chk.value - first_chk.value)
            if gap > (PCT_GAP if chk.unit == "pct" else REL_GAP * max(abs(first_chk.value), 1e-9)):
                out.setdefault(actor, []).append({"before": (first_chk, first_st), "after": (chk, st)})
                break
    return out


def coverage(session: Session, e: Election, now: datetime) -> list[Story]:
    """Historias desde que se abrio la ventana que hablan de elecciones o campana: del pais si es Espana;
    de cualquier medio si es otro pais, siempre que el titular lo nombre."""
    q = select(Story).where(
        Story.last_seen >= _since(e),
        Story.last_seen <= now + timedelta(days=1),
        or_(*(Story.title.ilike(w) for w in _STORY_WORDS)),
    )
    names = _country_words(e.country) if e.country != HOME else ()
    if names:
        q = q.where(or_(*(Story.title.ilike(f"%{n}%") for n in names)))
    else:
        q = q.where(Story.country == e.country)
    q = q.order_by(Story.priority.desc(), Story.last_seen.desc()).limit(COVERAGE * 4)
    rows = session.scalars(q).all()
    if names:
        rows = [s for s in rows if any(re.search(rf"\b{re.escape(n)}\b", normalize(s.title)) for n in names)]
    return [s for s in rows if _regional(e, s.title)][:COVERAGE]


def _country_words(iso: str) -> tuple[str, ...]:
    return tuple(n for n, code in _world_names().items() if code == iso and len(n) > 3)


def candidacy_rows(data: dict | None, e: Election) -> dict | None:
    """Formaciones de las candidaturas del BOE, enlazadas a la ficha del partido si esta en el registro."""
    if not data:
        return None
    known = {normalize(a.name).replace(" ", ""): a.slug for a in load_political() if a.country == e.country}
    rows = [{"f": f, "slug": known.get(f.key)} for f in data["formations"]]
    return {**data, "rows": rows}


def page(session: Session, e: Election, now: datetime, candidacies: dict | None = None) -> dict:
    today = now.date()
    return {
        "candidacies": candidacy_rows(candidacies, e),
        "e": e,
        "phase": e.phase(today),
        "days_left": e.days_left(today),
        "dates": key_dates(e, today),
        "parties": parties(session, e),
        "stories": coverage(session, e, now),
    }
