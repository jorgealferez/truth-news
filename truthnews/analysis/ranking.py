"""Lo que no cuadra: grandes falsedades, discrepancias, contradicciones y quien acumula mas (ADR 0027).

Todo se calcula en lectura con lo que ya hay en la base (veredictos con evidencia, comparativas por
historia, menciones), con el mismo metodo para cualquier medio, persona o partido:

- **Gravedad de una falsedad** = peso del veredicto x (1 + desviacion relativa frente al dato oficial,
  tope 2) x (1 + log2 de cuantos medios repiten la cifra) x actualidad (mitad cada 30 dias). Una cifra
  falsa que repiten diez medios pesa mas que la misma en uno; una desviacion del 50 % mas que una del 2 %.
- **Discrepancia entre medios**: historias con cifras en disputa (ADR 0016), por su puntuacion de
  contraste y con el rango de cada cifra.
- **Contradiccion**: el mismo actor (persona, partido o medio) da dos cifras distintas (> 5 %) del
  mismo indicador, territorio y periodo.
- **Quien acumula mas**: falsas o enganosas sobre comprobadas, siempre con el denominador a la vista.
  Nunca se dice "miente" de nadie: se dice que cifra dio, que dice el dato y donde comprobarlo.
"""

from __future__ import annotations

import math
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from truthnews.analysis.claims import indicator_name
from truthnews.analysis.compare import compare
from truthnews.models import Article, Claim, Entity, Story, Verification, utcnow

VERDICT_WEIGHT = {"falso": 3.0, "enganoso": 3.0, "impreciso": 1.5}
BAD = ("falso", "enganoso")
HALF_LIFE_DAYS = 30
CONTRADICTION_GAP = 0.05


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def deviation(claimed: float, official: float | None) -> float | None:
    """Desviacion relativa de la cifra dicha frente a la oficial (0,5 = un 50 % por encima o por debajo)."""
    if official is None:
        return None
    if official == 0:
        return 1.0 if claimed else 0.0
    return abs(claimed - official) / abs(official)


def gravity(verdict: str, dev: float | None, n_outlets: int, age_days: float) -> float:
    base = VERDICT_WEIGHT.get(verdict, 0.0)
    reach = 1 + math.log2(1 + max(n_outlets - 1, 0))
    recency = 0.5 ** (max(age_days, 0) / HALF_LIFE_DAYS)
    return round(base * (1 + min(dev or 0.0, 2.0)) * reach * recency, 3)


@dataclass
class Falsehood:
    indicator: str
    label: str
    geo: str
    claimed: float
    unit: str
    verdict: str
    official: float | None
    period: str | None
    source: str | None
    source_url: str | None
    deviation: float | None
    text: str
    first_seen: datetime
    outlets: list[str] = field(default_factory=list)
    speakers: list[tuple[int, str]] = field(default_factory=list)  # (id de entidad, nombre)
    story_id: int | None = None
    article_id: int | None = None
    score: float = 0.0


def falsehoods(
    session: Session,
    country: str | None = None,
    days: int = 180,
    limit: int = 20,
    now: datetime | None = None,
) -> list[Falsehood]:
    """Las cifras falsas, enganosas o imprecisas de mas peso; una fila por cifra aunque la den varios."""
    now = now or utcnow()
    q = (
        select(Claim, Verification, Article)
        .join(Verification, Verification.claim_id == Claim.id)
        .join(Article, Article.id == Claim.article_id)
        .options(joinedload(Claim.outlet), joinedload(Claim.speaker), joinedload(Verification.evidence))
        .where(
            Verification.verdict.in_(tuple(VERDICT_WEIGHT)),
            Article.published_at >= now - timedelta(days=days),
        )
    )
    if country:
        q = q.where(Claim.geo == country)
    groups: dict[tuple, Falsehood] = {}
    for claim, ver, art in session.execute(q).unique():
        ev = next((e for e in ver.evidence if e.value is not None), ver.evidence[0] if ver.evidence else None)
        key = (claim.indicator, claim.geo, claim.value, ver.verdict)
        published = _aware(art.published_at)
        f = groups.get(key)
        if f is None:
            f = groups[key] = Falsehood(
                indicator=claim.indicator,
                label=indicator_name(claim.indicator),
                geo=claim.geo,
                claimed=claim.value,
                unit=claim.unit,
                verdict=ver.verdict,
                official=ev.value if ev else None,
                period=ev.period if ev else None,
                source=ev.source if ev else None,
                source_url=ev.url if ev else None,
                deviation=deviation(claim.value, ev.value if ev else None),
                text=claim.text,
                first_seen=published,
                story_id=claim.story_id,
                article_id=claim.article_id,
            )
        if published < f.first_seen:
            f.first_seen, f.text, f.article_id = published, claim.text, claim.article_id
            f.story_id = claim.story_id or f.story_id
        if claim.outlet and claim.outlet.name not in f.outlets:
            f.outlets.append(claim.outlet.name)
        if claim.speaker and (claim.speaker.id, claim.speaker.name) not in f.speakers:
            f.speakers.append((claim.speaker.id, claim.speaker.name))
    for f in groups.values():
        f.score = gravity(
            f.verdict, f.deviation, len(f.outlets), (now - f.first_seen).total_seconds() / 86400
        )
    return sorted(groups.values(), key=lambda f: (-f.score, f.first_seen))[:limit]


@dataclass
class Discrepancy:
    story: Story
    disputes: list  # DisputeSummary
    n_outlets: int
    score: float


def discrepancies(
    session: Session, country: str | None = None, days: int = 14, limit: int = 12, now: datetime | None = None
) -> list[Discrepancy]:
    """Historias en las que los medios dan cifras distintas del mismo hecho, de mas a menos contraste."""
    now = now or utcnow()
    q = (
        select(Story)
        .where(Story.contrast_score > 0, Story.n_outlets >= 2, Story.last_seen >= now - timedelta(days=days))
        .order_by(Story.contrast_score.desc(), Story.last_seen.desc())
        .limit(limit * 3)
    )
    if country:
        q = q.where(Story.country == country)
    stories = [s for s in session.scalars(q) if (s.contrast or {}).get("disputas")]
    if not stories:
        return []
    arts: dict[int, list[Article]] = defaultdict(list)
    for a in session.scalars(
        select(Article)
        .options(joinedload(Article.outlet))
        .where(Article.story_id.in_([s.id for s in stories]))
    ):
        arts[a.story_id].append(a)
    out = []
    for st in stories:
        summaries = compare(arts.get(st.id, [])).dispute_summaries()
        if summaries:
            out.append(Discrepancy(st, summaries, st.n_outlets, st.contrast_score))
        if len(out) >= limit:
            break
    return out


@dataclass
class Contradiction:
    actor: str
    actor_kind: str  # medio | persona | partido | institucion | organizacion
    entity_id: int | None
    outlet_slug: str | None
    label: str
    geo: str
    period: str
    values: list[tuple[float, str, datetime, int]]  # (cifra, frase, fecha, id de noticia)
    unit: str


def contradictions(
    session: Session, days: int = 365, limit: int = 20, now: datetime | None = None
) -> list[Contradiction]:
    """El mismo actor da cifras distintas del mismo indicador, territorio y periodo."""
    now = now or utcnow()
    rows = session.execute(
        select(Claim, Verification, Article)
        .join(Verification, Verification.claim_id == Claim.id)
        .join(Article, Article.id == Claim.article_id)
        .options(joinedload(Claim.outlet), joinedload(Claim.speaker), joinedload(Verification.evidence))
        .where(Verification.verdict != "sin-datos", Article.published_at >= now - timedelta(days=days))
    ).unique()
    by_actor: dict[tuple, list] = defaultdict(list)
    for claim, ver, art in rows:
        period = claim.period or next((e.period for e in ver.evidence if e.period), None)
        if not period:
            continue
        actor = ("entidad", claim.speaker.id) if claim.speaker else ("medio", claim.outlet_id)
        by_actor[(actor, claim.indicator, claim.geo, period)].append((claim, art))
    out = []
    for (actor, indicator, geo, period), items in by_actor.items():
        values = sorted({c.value for c, _ in items})
        if len(values) < 2 or (values[-1] - values[0]) / max(abs(values[0]), 1e-9) <= CONTRADICTION_GAP:
            continue
        first = items[0][0]
        seen: dict[float, tuple] = {}
        for c, a in sorted(items, key=lambda x: x[1].published_at):
            seen.setdefault(c.value, (c.value, c.text, _aware(a.published_at), a.id))
        if actor[0] == "entidad":
            ent: Entity = first.speaker
            name, kind, eid, slug = ent.name, ent.kind, ent.id, None
        else:
            name, kind, eid, slug = first.outlet.name, "medio", None, first.outlet.slug
        out.append(
            Contradiction(
                name, kind, eid, slug, indicator_name(indicator), geo, period, list(seen.values()), first.unit
            )
        )
    out.sort(key=lambda c: (-len(c.values), -max(v[2] for v in c.values).timestamp()))
    return out[:limit]


@dataclass
class Tally:
    name: str
    kind: str
    entity_id: int | None
    outlet_slug: str | None
    checked: int = 0
    bad: int = 0
    imprecise: int = 0
    true: int = 0

    @property
    def share_bad(self) -> float:
        return self.bad / self.checked if self.checked else 0.0


def scoreboard(
    session: Session, days: int = 365, min_checked: int = 1, now: datetime | None = None
) -> dict[str, list[Tally]]:
    """Comprobadas y falsas o enganosas por persona/partido que las dice y por medio que las publica."""
    now = now or utcnow()
    people: dict[int, Tally] = {}
    outlets: dict[int, Tally] = {}
    for claim, ver in session.execute(
        select(Claim, Verification)
        .join(Verification, Verification.claim_id == Claim.id)
        .join(Article, Article.id == Claim.article_id)
        .options(joinedload(Claim.outlet), joinedload(Claim.speaker))
        .where(Verification.verdict != "sin-datos", Article.published_at >= now - timedelta(days=days))
    ):
        targets = [
            outlets.setdefault(claim.outlet_id, Tally(claim.outlet.name, "medio", None, claim.outlet.slug))
        ]
        if claim.speaker:
            sp = claim.speaker
            targets.append(people.setdefault(sp.id, Tally(sp.name, sp.kind, sp.id, None)))
        for t in targets:
            t.checked += 1
            t.bad += ver.verdict in BAD
            t.imprecise += ver.verdict == "impreciso"
            t.true += ver.verdict == "verdadero"

    def ordered(rows: dict[int, Tally]) -> list[Tally]:
        keep = [t for t in rows.values() if t.checked >= min_checked]
        return sorted(keep, key=lambda t: (-t.bad, -t.share_bad, -t.checked, t.name))

    return {"personas": ordered(people), "medios": ordered(outlets)}
