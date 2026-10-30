"""Investigaciones a demanda (ADR 0010): historias relacionadas, datos oficiales y cobertura mundial.

Sin IA el informe ya responde con material verificable (que se ha publicado, que dicen los datos y como
evoluciona la cobertura). Con IA se anade un analisis redactado con las mismas reglas de fundamento que
las piezas (ADR 0007): toda cifra del texto debe estar en el informe.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews.ai.client import AIClient, AIError
from truthnews.ai.writer import numbers_in
from truthnews.analysis.claims import indicators, world_countries
from truthnews.analysis.text import tokens
from truthnews.analysis.verify import Verifier
from truthnews.classify import normalize
from truthnews.data import gdelt
from truthnews.models import Article, Investigation, Story, utcnow

log = logging.getLogger(__name__)
DEFAULT_QUESTIONS = (
    "¿Por qué hay tantos disturbios y protestas en Europa últimamente?",
    "¿Qué influencia tiene Estados Unidos sobre Rusia, Israel y Ucrania según la cobertura y los datos?",
)
EUROPE_WORDS = ("europa", "europeo", "europea", "europeos", "europeas", "europe", "european")
EU_FOCUS = ("FR", "DE", "IT", "ES", "PT", "GR")
DATA_INDICATORS = ("paro", "inflacion", "precio_vivienda")
DOSSIER_STORIES = 10  # historias con dossier completo en la investigacion del foco (~10 000 tokens)
INVESTIGATION_SYSTEM = """\
Eres el equipo de investigacion de un medio de verificacion en espanol, riguroso y politicamente neutral.
Recibes una PREGUNTA y un INFORME cerrado: historias publicadas por varios medios, datos oficiales por
pais y la evolucion de la cobertura mundial (GDELT). Respondes a la pregunta solo con lo que hay en el
informe: toda cifra que escribas debe aparecer en el informe tal cual. Atribuyes cada afirmacion. Si el
informe trae "dossier", compara medio a medio con sus titulares, resumenes y cifras en disputa. Si el
informe no permite responder algo, lo dices en "lo_que_no_sabemos". Planteas hipotesis y las evaluas con
la evidencia a favor y en contra, sin tomar partido por gobiernos, partidos ni ideologias. Espanol de
Espana, claro, para el gran publico."""


def seed_defaults(session: Session) -> int:
    if session.scalars(select(Investigation.id).limit(1)).first():
        return 0
    session.add_all(Investigation(question=q) for q in DEFAULT_QUESTIONS)
    session.flush()
    return len(DEFAULT_QUESTIONS)


def investigation_schema() -> dict:
    s, arr = {"type": "string"}, lambda item: {"type": "array", "items": item}

    def obj(props: dict) -> dict:
        return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}

    return obj(
        {
            "titular": s,
            "respuesta_corta": s,
            "contexto": arr(s),
            "que_dicen_los_datos": arr(obj({"dato": s, "fuente": s})),
            "que_cuentan_los_medios": arr(s),
            "hipotesis": arr(obj({"hipotesis": s, "a_favor": s, "en_contra": s, "evaluacion": s})),
            "lo_que_no_sabemos": arr(s),
            "conclusion": s,
        }
    )


def countries_in(text_n: str) -> list[str]:
    text_n = re.sub(r"[^\w\s]", " ", text_n)
    out = [
        iso
        for iso, names in indicators()["geo_names"].items()
        if any(f" {normalize(n)} " in f" {text_n} " for n in names)
    ]
    out += [
        iso
        for iso, names in world_countries().items()
        if iso not in out and any(f" {n} " in f" {text_n} " for n in names)
    ]
    if any(w in text_n.split() for w in EUROPE_WORDS):
        out += [g for g in ("EU", *EU_FOCUS) if g not in out]
    return out


def related_stories(
    session: Session, question: str, geos: list[str], days: int = 30, limit: int = 20
) -> list[Story]:
    """Historias con >= 2 medios relacionadas con la pregunta por terminos y paises."""
    wanted = set(tokens(question))
    since = utcnow() - timedelta(days=days)
    rows = session.execute(
        select(Story, Article.title, Article.summary)
        .join(Article, Article.story_id == Story.id)
        .where(Story.n_outlets >= 2, Story.last_seen >= since)
    ).all()
    text: dict[int, list[str]] = {}
    stories: dict[int, Story] = {}
    for st, title, summary in rows:
        stories[st.id] = st
        text.setdefault(st.id, []).append(f"{title} {summary or ''}")
    scored = []
    for sid, parts in text.items():
        blob = " ".join(parts)
        overlap = len(wanted & set(tokens(blob)))
        geo_hit = bool(set(countries_in(normalize(blob))) & set(geos))
        score = overlap + (1 if geo_hit else 0)
        if score >= 2:
            scored.append((score, stories[sid].n_outlets, stories[sid]))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    return [st for _, _, st in scored[:limit]]


# GDELT indexa la prensa mundial traducida al ingles: la consulta se construye en ingles (medido el
# 2026-10-18: "protestas europa" -> 0 puntos; "riots europe" -> 19).
EN_TERMS = {
    "disturbios": "riots",
    "protestas": "protests",
    "manifestaciones": "protests",
    "huelga": "strike",
    "huelgas": "strikes",
    "europa": "europe",
    "inflacion": "inflation",
    "vivienda": "housing",
    "inmigracion": "immigration",
    "migrantes": "migrants",
    "elecciones": "elections",
    "guerra": "war",
    "sanciones": "sanctions",
    "paro": "unemployment",
    "desempleo": "unemployment",
    "rusia": "russia",
    "ucrania": "ukraine",
    "israel": "israel",
    "gaza": "gaza",
    "iran": "iran",
    "china": "china",
    "francia": "france",
    "alemania": "germany",
    "italia": "italy",
    "espana": "spain",
    "portugal": "portugal",
    "marruecos": "morocco",
    "aranceles": "tariffs",
    "energia": "energy",
    "violencia": "violence",
    "terrorismo": "terrorism",
    "corrupcion": "corruption",
    "clima": "climate",
    "incendios": "wildfires",
    "tren": "train",
    "trenes": "train",
    "ferroviario": "rail",
    "accidente": "accident",
    "choque": "collision",
    "descarrilamiento": "derailment",
}
EN_PHRASES = {
    "estados unidos": "united states",
    "union europea": "european union",
    "reino unido": "united kingdom",
}


def gdelt_query(question: str) -> str:
    qn = " " + re.sub(r"[^\w\s]", " ", normalize(question)) + " "
    terms = [en for es, en in EN_PHRASES.items() if f" {es} " in qn]
    for w in qn.split():
        en = EN_TERMS.get(w)
        if en and en not in terms:
            terms.append(en)
    return " ".join(f'"{t}"' if " " in t else t for t in terms[:4])


def build_report(
    session: Session,
    inv: Investigation,
    verifier: Verifier,
    timeline: Callable[..., list[dict]] = gdelt.timeline,
    stories: list[Story] | None = None,
) -> dict:
    """Con `stories` (las del foco, ADR 0056) el informe se ciñe a ellas y lleva su dossier medio a medio
    en vez de buscar por terminos, que mezclaba historias ajenas; los indicadores por pais no aplican."""
    from truthnews.ai.threads import story_brief  # threads importa este modulo

    qn = normalize(inv.question)
    geos = countries_in(qn)
    deep = stories is not None
    if not deep:
        stories = related_stories(session, inv.question, geos)
    data = []
    for geo in [] if deep else geos[:8]:
        for ind in DATA_INDICATORS:
            obs = verifier.observation(ind, geo)
            if obs is None or obs.is_stale():
                continue
            recent = dict(sorted(obs.history.items())[-6:]) if obs.history else {obs.period: obs.value}
            recent = {k: round(v, 2) for k, v in recent.items()}
            data.append(
                {
                    "indicador": obs.label,
                    "pais": geo,
                    "periodo": obs.period,
                    "valor": round(obs.value, 2),
                    "fuente": obs.source,
                    "url": obs.url,
                    "serie_reciente": recent,
                }
            )
    query = gdelt_query(inv.question)
    points = timeline(query, "30d") if query else []
    values = [p["value"] for p in points if isinstance(p.get("value"), int | float)]
    coverage = {
        "consulta": query,
        "puntos": len(values),
        "media": round(sum(values) / len(values), 4) if values else None,
        "ultimo": values[-1] if values else None,
        "maximo": max(values) if values else None,
        "fuente": "GDELT DOC 2.0 (porcentaje de la cobertura mundial monitorizada)",
    }
    report = {
        "pregunta": inv.question,
        "paises": geos,
        "historias": [
            {
                "id": s.id,
                "titular": s.title,
                "medios": s.n_outlets,
                "ultima": s.last_seen.strftime("%d/%m/%Y"),
            }
            for s in stories
        ],
        "datos": data,
        "cobertura_mundial": coverage,
        "metodo": (
            "Historias de los ultimos 30 dias contadas por al menos 2 medios que comparten terminos con "
            "la pregunta; datos oficiales mas recientes de los paises implicados; volumen diario de "
            "cobertura mundial en GDELT."
        ),
    }
    if deep:
        report["dossier"] = [story_brief(session, s) for s in stories[:DOSSIER_STORIES]]
        report["metodo"] = (
            "Historias del suceso en foco de las ultimas 72 h contadas por al menos 2 medios, con el "
            "titular y el resumen de cada medio y las cifras en las que discrepan; volumen diario de "
            "cobertura mundial en GDELT."
        )
    return report


def process_pending(
    session: Session,
    verifier: Verifier | None = None,
    ai: AIClient | None = None,
    timeline: Callable[..., list[dict]] = gdelt.timeline,
    limit: int = 2,
    question: str | None = None,
    stories: list[Story] | None = None,
) -> dict:
    verifier = verifier or Verifier()
    q = select(Investigation).where(Investigation.status == "pendiente")
    if question is not None:  # solo la de esa pregunta (la del foco, ADR 0056)
        q = q.where(Investigation.question == question)
    pending = list(session.scalars(q.order_by(Investigation.created_at).limit(limit)))
    done = failed = 0
    for inv in pending:
        inv.status, inv.updated_at = "en-curso", utcnow()
        session.flush()
        try:
            report = build_report(session, inv, verifier, timeline, stories)
            if ai is not None:
                try:
                    res = ai.structured(
                        INVESTIGATION_SYSTEM,
                        f"PREGUNTA: {inv.question}\n\nINFORME (JSON):\n"
                        + json.dumps(report, ensure_ascii=False),
                        investigation_schema(),
                    )
                    unsupported = sorted(
                        n
                        for n in numbers_in(json.dumps(res.data, ensure_ascii=False))
                        - numbers_in(json.dumps(report, ensure_ascii=False))
                        if not (float(n).is_integer() and (float(n) <= 10 or 1990 <= float(n) <= 2035))
                    )
                    key = "analisis" if not unsupported else "analisis_en_revision"
                    report[key] = res.data
                    report["fundamento"] = {"cifras_sin_fuente": unsupported, "ok": not unsupported}
                    report["modelo"] = res.model
                except AIError as exc:
                    report["analisis_error"] = str(exc)
            inv.report, inv.status, inv.error = report, "publicada", None
            done += 1
        except Exception as exc:  # una investigacion fallida no tumba el ciclo; queda registrada
            log.exception("investigacion %s fallida", inv.id)
            inv.status, inv.error = "error", f"{type(exc).__name__}: {exc}"[:500]
            failed += 1
        inv.updated_at = utcnow()
        session.commit()  # cada investigacion queda guardada aunque el ciclo se corte
    return {"processed": done, "failed": failed}
