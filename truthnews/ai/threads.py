"""Hilos (ADR 0013): de la noticia de hoy a lo que se dijo y paso antes, y a lo que vino despues.

Dos llamadas a la IA con un corpus en medio:
1. PLAN: actores, busquedas y periodos a investigar y posibles conexiones (hipotesis, no hechos).
2. CORPUS: historias propias del ultimo ano, hemeroteca mundial de GDELT y contexto de Wikipedia, todo
   con fecha y URL, numerado (S1, G1, W1...).
3. HILO: cronologia, quien dijo que y conexiones; cada elemento cita ids del corpus. Lo que no cita nada
   valido se descarta, y una cifra que no esta en el corpus manda el hilo a revision (ADR 0007).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews.ai.client import AIClient, AIError
from truthnews.ai.writer import numbers_in, write_thread_piece
from truthnews.analysis.compare import compare
from truthnews.data import gdelt, wikipedia
from truthnews.investigate import related_stories
from truthnews.models import Story, Thread, utcnow
from truthnews.web import queries

log = logging.getLogger(__name__)
REFRESH_AFTER = timedelta(hours=12)
MAX_GDELT_CALLS = 6
MAX_WIKI_QUERIES = 3
MAX_EVENTS = 25
MAX_LINKS = 8

PLAN_SYSTEM = """\
Eres el jefe de investigacion de un medio de verificacion en espanol, riguroso y politicamente neutral.
Recibes una historia de hoy tal como la cuentan varios medios. Preparas la investigacion de su contexto:
que hechos anteriores pueden explicarla (meses o anos atras), que actores intervienen, y que relaciones
no evidentes conviene comprobar (decisiones diplomaticas, economicas, militares o politicas que parecen
ajenas y pueden estar conectadas). Las conexiones que propones son HIPOTESIS a comprobar, no hechos.
Las consultas para la hemeroteca mundial (GDELT) van en INGLES, con 2-4 palabras clave y sin comillas
salvo nombres compuestos; las de Wikipedia, en espanol. Los periodos van en formato AAAA-MM-DD entre
2017-01-01 y hoy. No tomas partido por gobiernos, partidos ni ideologias."""

THREAD_SYSTEM = """\
Eres el equipo de investigacion de un medio de verificacion en espanol, riguroso y politicamente neutral.
Recibes una historia de hoy, un plan con hipotesis y un CORPUS cerrado de fuentes numeradas (S = historias
publicadas por varios medios espanoles, G = hemeroteca mundial con fecha, W = enciclopedia). Construyes el
hilo: que se decia, que paso, que hubo por el camino, quien dijo que y que vino despues.
Reglas: cada hecho, declaracion y conexion cita en "fuentes" los ids del corpus que lo sostienen; si algo
no esta en el corpus, no lo escribes. Toda cifra que escribas debe aparecer en el corpus tal cual. Una
conexion es "probada" solo si una fuente la afirma explicitamente; "probable" si varias fuentes la hacen
verosimil por fechas y actores; "especulativa" en otro caso, y entonces lo dices. Atribuyes cada
declaracion a quien la hizo. Lo que el corpus no permite saber va en "lo_que_no_sabemos". Sin adjetivos
valorativos ni toma de partido. Espanol de Espana, claro, para el gran publico; frases cortas."""


def _obj(props: dict) -> dict:
    return {"type": "object", "properties": props, "required": list(props), "additionalProperties": False}


def _arr(item: dict) -> dict:
    return {"type": "array", "items": item}


S = {"type": "string"}
IDS = _arr(S)


def plan_schema() -> dict:
    return _obj(
        {
            "tema": S,
            "pregunta_central": S,
            "actores": _arr(S),
            "consultas_hemeroteca": _arr(_obj({"consulta": S, "desde": S, "hasta": S, "motivo": S})),
            "consultas_enciclopedia": _arr(S),
            "hipotesis": _arr(_obj({"hecho": S, "por_que_comprobarlo": S})),
        }
    )


def thread_schema() -> dict:
    return _obj(
        {
            "titular": S,
            "resumen": S,
            "por_que_ahora": S,
            "cronologia": _arr(
                _obj(
                    {
                        "fecha": S,
                        "hecho": S,
                        "quien": S,
                        "tipo": {"type": "string", "enum": ["dijo", "hizo", "dato", "consecuencia"]},
                        "fuentes": IDS,
                    }
                )
            ),
            "que_dijo_quien": _arr(_obj({"quien": S, "que": S, "fecha": S, "fuentes": IDS})),
            "conexiones": _arr(
                _obj(
                    {
                        "de": S,
                        "a": S,
                        "explicacion": S,
                        "solidez": {"type": "string", "enum": ["probada", "probable", "especulativa"]},
                        "fuentes": IDS,
                    }
                )
            ),
            "lo_que_no_sabemos": _arr(S),
        }
    )


def story_brief(session: Session, st: Story) -> dict:
    """La historia de hoy como la cuentan los medios: titulares por medio y cifras en disputa."""
    arts = queries.story_articles(session, st.id)
    comp = compare(arts)
    latest = {a.outlet.name: a for a in arts}
    return {
        "titular": st.title,
        "desde": f"{st.first_seen:%Y-%m-%d}",
        "hasta": f"{st.last_seen:%Y-%m-%d}",
        "medios": [
            {"medio": name, "titular": a.title, "resumen": (a.summary or "")[:300]}
            for name, a in latest.items()
        ][:20],
        "cifras_en_disputa": {
            d.noun: {"minimo": d.low, "maximo": d.high, "medios": d.n_outlets}
            for d in comp.dispute_summaries()
        },
        "a_quien_senalan": comp.blame,
    }


def _date(value: str, default: datetime) -> datetime:
    try:
        return datetime.strptime(value[:10], "%Y-%m-%d").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return default


def build_corpus(
    session: Session,
    st: Story,
    plan: dict,
    now: datetime | None = None,
    articles: Callable[..., list[dict]] = gdelt.articles,
    encyclopedia: Callable[..., list[dict]] = wikipedia.search,
) -> list[dict]:
    """Fuentes numeradas con fecha y URL. Una fuente que falla no tumba el hilo: se usa lo que haya."""
    now = now or utcnow()
    corpus: list[dict] = []
    question = " ".join([plan.get("tema", ""), *plan.get("actores", [])])
    for s in related_stories(session, question, [], days=365, limit=15):
        if s.id == st.id:
            continue
        corpus.append(
            {
                "id": f"S{s.id}",
                "fecha": f"{s.first_seen:%Y-%m-%d}",
                "titular": s.title,
                "medios": s.n_outlets,
                "url": f"/historia/{s.id}",
            }
        )
    seen_urls: set[str] = set()
    g = 0
    for q in plan.get("consultas_hemeroteca", [])[:MAX_GDELT_CALLS]:
        start = _date(q.get("desde", ""), now - timedelta(days=365))
        end = min(_date(q.get("hasta", ""), now), now)
        if start >= end:
            continue
        try:
            found = articles(q["consulta"], start, end, max_records=15)
        except Exception as exc:  # una fuente externa caida no tumba el hilo; queda en el registro
            log.warning("hemeroteca %r: %s", q.get("consulta"), exc)
            continue
        for a in found:
            if not a["url"] or a["url"] in seen_urls or not a["title"]:
                continue
            seen_urls.add(a["url"])
            g += 1
            corpus.append(
                {
                    "id": f"G{g}",
                    "fecha": f"{a['date']:%Y-%m-%d}",
                    "titular": a["title"],
                    "medio": a["domain"],
                    "idioma": a["language"],
                    "url": a["url"],
                }
            )
    w = 0
    for q in plan.get("consultas_enciclopedia", [])[:MAX_WIKI_QUERIES]:
        try:
            pages = encyclopedia(q, limit=2)
        except Exception as exc:  # idem
            log.warning("enciclopedia %r: %s", q, exc)
            continue
        for p in pages:
            if p["url"] in seen_urls:
                continue
            seen_urls.add(p["url"])
            w += 1
            corpus.append({"id": f"W{w}", "titulo": p["title"], "extracto": p["extract"], "url": p["url"]})
    return corpus


def ground(content: dict, corpus: list[dict], brief: dict) -> tuple[dict, dict]:
    """Quita lo que no cita fuentes del corpus y comprueba que las cifras esten en el corpus."""
    ids = {c["id"] for c in corpus}
    dropped = 0
    clean = dict(content)
    for key, cap in (("cronologia", MAX_EVENTS), ("que_dijo_quien", MAX_EVENTS), ("conexiones", MAX_LINKS)):
        kept = []
        for item in content.get(key, []):
            valid = [f for f in item.get("fuentes", []) if f in ids]
            if valid:
                kept.append({**item, "fuentes": valid})
            else:
                dropped += 1
        clean[key] = kept[:cap]
    if clean.get("cronologia"):
        clean["cronologia"] = sorted(clean["cronologia"], key=lambda e: e.get("fecha", ""))
    source_numbers = numbers_in(json.dumps([corpus, brief], ensure_ascii=False, default=str))
    unsupported = sorted(
        n
        for n in numbers_in(json.dumps(clean, ensure_ascii=False)) - source_numbers
        if not (float(n).is_integer() and (float(n) <= 31 or 1990 <= float(n) <= 2035))
    )
    total = sum(len(content.get(k, [])) for k in ("cronologia", "que_dijo_quien", "conexiones"))
    ok = not unsupported and len(clean.get("cronologia", [])) >= 2 and dropped <= total / 2
    return clean, {"sin_fuente_descartados": dropped, "cifras_sin_fuente": unsupported, "ok": ok}


def build_thread(
    session: Session,
    st: Story,
    ai: AIClient,
    articles: Callable[..., list[dict]] = gdelt.articles,
    encyclopedia: Callable[..., list[dict]] = wikipedia.search,
) -> Thread:
    brief = story_brief(session, st)
    today = f"{utcnow():%Y-%m-%d}"
    plan_res = ai.structured(
        PLAN_SYSTEM,
        f"HOY: {today}\nHISTORIA (JSON):\n" + json.dumps(brief, ensure_ascii=False),
        plan_schema(),
    )
    plan = plan_res.data
    corpus = build_corpus(session, st, plan, articles=articles, encyclopedia=encyclopedia)
    user = (
        f"HOY: {today}\nHISTORIA (JSON):\n{json.dumps(brief, ensure_ascii=False)}\n\n"
        f"PLAN (hipotesis, no hechos):\n{json.dumps(plan, ensure_ascii=False)}\n\n"
        f"CORPUS (JSON):\n{json.dumps(corpus, ensure_ascii=False)}"
    )
    res = ai.structured(THREAD_SYSTEM, user, thread_schema())
    content, grounding = ground(res.data, corpus, brief)
    thread = session.scalars(select(Thread).where(Thread.anchor_story_id == st.id)).first() or Thread(
        anchor_story_id=st.id, country=st.country
    )
    thread.title = (content.get("titular") or st.title)[:300]
    thread.status = "publicado" if grounding["ok"] else "revision"
    thread.plan, thread.content, thread.sources, thread.grounding = plan, content, corpus, grounding
    thread.model = res.model
    thread.usage = {"plan": plan_res.usage, "hilo": res.usage}
    thread.error, thread.updated_at = None, utcnow()
    session.add(thread)
    session.flush()
    return thread


def run(
    session: Session,
    ai: AIClient,
    country: str = "ES",
    limit: int = 2,
    stories: list[Story] | None = None,
    refresh: timedelta = REFRESH_AFTER,
    **sources,
) -> dict:
    """Hilos para las historias de cabecera (o las dadas, p. ej. las del foco, ADR 0056) que no lo tienen o
    lo tienen de hace mas de `refresh`."""
    done = revision = failed = pieces = 0
    candidates = queries.top_stories(session, country=country, limit=8) if stories is None else stories
    for st in candidates:
        if done + failed >= limit:
            break
        existing = session.scalars(select(Thread).where(Thread.anchor_story_id == st.id)).first()
        updated = existing.updated_at if existing else None
        if updated and (updated if updated.tzinfo else updated.replace(tzinfo=UTC)) > utcnow() - refresh:
            continue
        try:
            thread = build_thread(session, st, ai, **sources)
        except AIError as exc:
            log.warning("hilo de la historia %s no generado: %s", st.id, exc)
            failed += 1
            continue
        session.commit()  # cada hilo queda guardado aunque el ciclo se corte
        done += 1
        revision += thread.status == "revision"
        try:  # su pieza propia (ADR 0020): si falla, el hilo ya esta guardado
            pieces += write_thread_piece(session, thread, ai) is not None
            session.commit()
        except AIError as exc:
            log.warning("pieza del hilo %s no generada: %s", thread.id, exc)
    return {
        "threads": done,
        "threads_in_revision": revision,
        "threads_failed": failed,
        "thread_pieces": pieces,
    }
