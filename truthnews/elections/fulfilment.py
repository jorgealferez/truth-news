"""Lo prometido frente a lo hecho por quien goberno (18c, ADR 0040): primero el codigo, la IA solo lo justo.

Decision del usuario (2026-10-19): combinar los datos oficiales con la IA "para obtener mejores resultados y
reducir el coste en IA a lo necesario". Por eso hay tres pasos y solo el ultimo gasta IA:

1. `dato-v1` (codigo): si la promesa fija una meta de un indicador oficial ("bajaremos la inflacion al
   2 %"), se compara con el ultimo dato oficial. Es un veredicto del codigo con datos (ADR 0007): se publica.
2. `boe-candidatas-v1` (codigo): normas estatales del BOE (legislacion consolidada) publicadas mientras ese
   partido gobernaba cuyo titulo contiene al menos dos palabras de tema de la promesa. Medido: solo ~1 de
   cada 6 trata de verdad de lo prometido, asi que no se publican; son las candidatas para el paso 3.
3. `ia-boe-v1` (IA, revisado): solo para promesas con candidatas y sin veredicto de datos. La IA lee la
   promesa y los titulos de sus candidatas, en lotes, y propone "cumplida", "parcial" o "sin dato
   comprobable" citando solo normas de la lista. El codigo valida la cita. La propuesta queda pendiente
   hasta que una persona la revisa en /admin; solo entonces se publica, marcada como asistida por IA.

Solo se mide a quien goberno tras la eleccion de la promesa (registro `governments`): los demas partidos no
tuvieron el Gobierno para cumplirla. La pagina lo explica. Nunca se escribe "mintio": no cumplir una
promesa no es una afirmacion falsa.
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime
from functools import lru_cache

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews import registry
from truthnews.analysis import claims as claims_mod
from truthnews.analysis.text import STOPWORDS
from truthnews.analysis.verify import Verifier
from truthnews.classify import normalize
from truthnews.data import boe_legislacion as boe
from truthnews.models import Promise, PromiseCheck

log = logging.getLogger(__name__)

METHOD_DATA = "dato-v1"
METHOD_CANDIDATES = "boe-candidatas-v1"
METHOD_AI = "ia-boe-v1"
PENDING = f"{METHOD_AI}:pendiente"
REJECTED = f"{METHOD_AI}:rechazada"
PUBLIC_METHODS = (METHOD_DATA, METHOD_AI)
MIN_HITS = 2
MAX_CANDIDATES = 5
_WORD = re.compile(r"[a-zñ]{5,}")
# Palabras de programa que no distinguen nada: con ellas cualquier norma "coincidiria".
_GENERIC_TEXT = """
    garantizar impulsar promover medidas medida politica politicas nacional estado espana espanol
    espanola publico publica publicos publicas sistema sistemas mejorar crear desarrollar todas todos
    personas derecho derechos acceso nuevo nueva nuevos nuevas marco ambito forma traves manera aprobar
    reforma reformas social sociales general generales ademas especial especialmente objetivo objetivos
    materia ambitos asegurar establecer situacion recursos proceso procesos ciudadania ciudadanos sector
    sectores realizar estrategia estrategias programa programas proyecto proyectos fomentar favorecer
    reforzar ampliar apoyo apoyar vamos puedan
"""
# Palabras que aparecen en muchisimos titulos del BOE: no bastan para decir que una norma trata de algo.
_BOE_COMMON_TEXT = """
    proteccion reconocimiento reconocimientos creacion europea europeo europeos union condiciones regimen
    organizacion funcionamiento regulacion modificacion aprobacion desarrollo servicios servicio normas
    procedimiento reglamento texto refundido directiva accion integral centros instituciones comunidad
    produccion internacional internacionales situaciones legislacion instrumentos revision reducir precios
    impacto crisis lucha casos actual actuales medidas urgentes
"""
GENERIC = frozenset(_GENERIC_TEXT.split())
BOE_COMMON = frozenset(_BOE_COMMON_TEXT.split())
_DOWN = re.compile(r"\b(reduci\w*|baja\w*|rebaja\w*|disminui\w*|por debajo|no superar|menos de|maximo)\b")
_UP = re.compile(r"\b(aumenta\w*|sub\w*|eleva\w*|incrementa\w*|alcanza\w*|al menos|por encima|minimo)\b")

AI_SYSTEM = """Revisas promesas electorales de un partido que gobernó, una a una, frente a normas del \
Boletín Oficial del Estado publicadas mientras gobernaba. De cada norma solo tienes su título, su rango y su \
fecha.

Para cada promesa decide:
- "cumplida": una norma de su lista hace, por su título, exactamente lo que se prometió.
- "parcial": una norma de su lista hace una parte clara de lo prometido.
- "sin-datos": ninguna norma de la lista trata de lo prometido o el título no basta para saberlo.

Reglas:
- Usa solo las normas de la lista de esa promesa y cítalas por su identificador (BOE-A-...).
- Si dudas, "sin-datos". Que no haya norma no significa que no se cumpliera: no lo afirmes.
- La explicación, en castellano, en una o dos frases y sin adjetivos ni intenciones: qué hace la norma \
citada frente a lo prometido.
"""

AI_SCHEMA = {
    "type": "object",
    "properties": {
        "items": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "integer"},
                    "status": {"type": "string", "enum": ["cumplida", "parcial", "sin-datos"]},
                    "norms": {"type": "array", "items": {"type": "string"}},
                    "explanation": {"type": "string"},
                },
                "required": ["id", "status", "norms", "explanation"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["items"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class Government:
    country: str
    name: str
    start: date
    end: date | None
    parties: tuple[str, ...]
    election_kind: str
    election_year: int
    source_label: str
    source_url: str


def _d(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def load_governments(raw: list | None = None) -> tuple[Government, ...]:
    if raw is None:
        raw = registry._load_yaml(registry.REGISTRY_DIR / "elections.yaml").get("governments") or []
    return tuple(
        Government(
            country=g["country"],
            name=g.get("name", g["country"]),
            start=_d(g["from"]),
            end=_d(g.get("to")),
            parties=tuple(g["parties"]),
            election_kind=g["election"]["kind"],
            election_year=int(g["election"]["year"]),
            source_label=g["source"]["label"],
            source_url=g["source"]["url"],
        )
        for g in raw
    )


@lru_cache(maxsize=1)
def governments() -> tuple[Government, ...]:
    return load_governments()


def government_of(p: Promise, govs: tuple[Government, ...] | None = None) -> Government | None:
    """El Gobierno que formo este partido tras la eleccion de la promesa de su programa (si lo formo)."""
    for g in governments() if govs is None else govs:
        if (
            p.program_id is not None
            and g.country == p.country
            and p.actor in g.parties
            and p.election_kind == g.election_kind
            and p.election_year == g.election_year
        ):
            return g
    return None


def words(text: str) -> list[str]:
    out = []
    for w in _WORD.findall(normalize(text)):
        if w in STOPWORDS or w in GENERIC or w.endswith(("remos", "aremos", "mente", "ando", "iendo")):
            continue
        out.append(w)
    return list(dict.fromkeys(out))


def key_terms(text: str, df: Counter, n_docs: int, n: int = 4) -> list[str]:
    """Las primeras palabras de contenido de la promesa (lo prometido va tras el verbo), sin las de casi
    todas las promesas del programa ni las muy comunes en los titulos del BOE."""
    ceiling = max(3, int(0.15 * n_docs))
    return [w for w in words(text) if w not in BOE_COMMON and df.get(w, 0) <= ceiling][:n]


def hits(norm: boe.Norm, terms: list[str]) -> int:
    title = set(_WORD.findall(normalize(norm.title)))
    return sum(1 for t in terms if t in title)


def candidates(p: Promise, g: Government, terms: list[str], today: date, search=boe.search) -> list[dict]:
    """Normas del BOE del periodo de gobierno cuyo titulo tiene al menos MIN_HITS terminos de la promesa."""
    if len(terms) < MIN_HITS:
        return []
    until = min(g.end or today, today)
    found = [(hits(n, terms), n) for n in search(terms, g.start, until)]
    found = sorted((x for x in found if x[0] >= MIN_HITS), key=lambda x: (-x[0], x[1].published))
    return [
        {"source": "BOE", "id": n.id, "label": n.title, "url": n.url, "period": n.published.isoformat(),
         "rank": n.rank, "hits": h}
        for h, n in found[:MAX_CANDIDATES]
    ]


def target_of(text: str, country: str, year: int) -> tuple[str, float, str, str] | None:
    """(indicador, meta, unidad, 'max'|'min') de una promesa con meta medible, o None."""
    found = claims_mod.extract(text, "es", country, year)
    if len(found) != 1:
        return None
    t = normalize(text)
    down, up = bool(_DOWN.search(t)), bool(_UP.search(t))
    if down == up:  # sin direccion o con las dos: no se adivina
        return None
    c = found[0]
    return c.indicator, c.value, c.unit, "max" if down else "min"


def data_check(p: Promise, g: Government, verifier: Verifier, today: date) -> dict | None:
    target = target_of(p.text, p.country, p.election_year or today.year)
    if not target:
        return None
    indicator, goal, unit, sense = target
    name = claims_mod.indicator_name(indicator)
    obs = verifier.observation(indicator, p.country)
    if obs is None:
        return {
            "status": "sin-datos",
            "explanation": f"No hay serie oficial disponible de «{name}» para comprobar la meta.",
            "evidence": [],
        }
    met = obs.value <= goal if sense == "max" else obs.value >= goal
    governing = g.end is None or g.end >= today
    status = "cumplida" if met else ("en-curso" if governing else "no-cumplida")
    pct = " %" if unit == "pct" else ""
    word = "como máximo" if sense == "max" else "al menos"
    explanation = (
        f"Meta prometida: «{name}» {word} {goal:g}{pct}. Último dato oficial ({obs.period}, {obs.source}): "
        f"{obs.value:g}{pct}."
    )
    return {
        "status": status,
        "explanation": explanation,
        "evidence": [{"source": obs.source, "label": obs.label, "url": obs.url, "period": obs.period}],
    }


def _checked(session: Session, method_prefix: str) -> set[int]:
    return set(
        session.scalars(select(PromiseCheck.promise_id).where(PromiseCheck.method.startswith(method_prefix)))
    )


def rules_step(
    session: Session, limit: int, today: date, search=boe.search, verifier: Verifier | None = None,
    pause: float = 0.3, govs: tuple[Government, ...] | None = None,
) -> dict:
    """Pasos 1 y 2, sin IA: dato oficial y normas candidatas de las promesas de quien goberno."""
    verifier = verifier or Verifier()
    done = _checked(session, METHOD_CANDIDATES)
    pending = [
        p
        for p in session.scalars(select(Promise).where(Promise.program_id.is_not(None)).order_by(Promise.id))
        if p.id not in done and government_of(p, govs)
    ][:limit]
    summary = {"checked": 0, "by_data": 0, "with_candidates": 0, "errors": 0}
    dfs: dict[int, tuple[Counter, int]] = {}
    for p in pending:
        if p.program_id not in dfs:
            texts = list(session.scalars(select(Promise.text).where(Promise.program_id == p.program_id)))
            dfs[p.program_id] = (Counter(w for t in texts for w in set(words(t))), len(texts))
        df, n_docs = dfs[p.program_id]
        g = government_of(p, govs)
        try:
            found = candidates(p, g, key_terms(p.text, df, n_docs), today, search=search)
        except httpx.HTTPError:
            summary["errors"] += 1  # el BOE no respondio: se reintenta en el siguiente ciclo
            continue
        by_data = data_check(p, g, verifier, today)
        if by_data:
            session.add(PromiseCheck(promise_id=p.id, method=METHOD_DATA, **by_data))
            summary["by_data"] += 1
        session.add(
            PromiseCheck(
                promise_id=p.id,
                method=METHOD_CANDIDATES,
                status="sin-datos",
                explanation=f"{len(found)} normas candidatas por el titulo (sin valorar).",
                evidence=found,
            )
        )
        summary["checked"] += 1
        summary["with_candidates"] += bool(found)
        if pause:
            time.sleep(pause)
    return summary


def ai_queue(session: Session, govs: tuple[Government, ...] | None = None) -> list[tuple[Promise, list]]:
    """Promesas que necesitan IA: con candidatas, sin veredicto de datos y sin propuesta previa. Primero las
    de candidatas con mas terminos en comun (donde la IA mas probablemente encuentre algo)."""
    by_data = _checked(session, METHOD_DATA)
    by_ai = _checked(session, METHOD_AI)
    rows = session.execute(
        select(Promise, PromiseCheck)
        .join(PromiseCheck, PromiseCheck.promise_id == Promise.id)
        .where(PromiseCheck.method == METHOD_CANDIDATES)
    ).all()
    out = [
        (p, chk.evidence)
        for p, chk in rows
        if chk.evidence and p.id not in by_data and p.id not in by_ai and government_of(p, govs)
    ]
    return sorted(out, key=lambda x: (-max(c.get("hits", 0) for c in x[1]), x[0].id))


def ai_prompt(batch: list[tuple[Promise, list[dict]]], g: Government) -> str:
    lines = [f"Gobierno: {g.name}, del {g.start:%d/%m/%Y} al {(g.end or date.today()):%d/%m/%Y}.", ""]
    for p, cands in batch:
        lines.append(f"Promesa {p.id} ({p.actor}, programa de {p.election_year}): «{p.text}»")
        for c in cands:
            lines.append(f"  - {c['id']} | {c['rank']} | {c['period']} | {c['label']}")
        lines.append("")
    return "\n".join(lines)


def validate(item: dict, cands: list[dict]) -> dict:
    """La IA solo puede citar normas de la lista; sin norma citada no hay "cumplida" ni "parcial"."""
    allowed = {c["id"]: c for c in cands}
    cited = [allowed[n] for n in dict.fromkeys(item.get("norms") or []) if n in allowed]
    status = item.get("status")
    if status not in ("cumplida", "parcial") or not cited:
        status, cited = "sin-datos", []
    explanation = " ".join(str(item.get("explanation") or "").split())[:600]
    if status == "sin-datos":
        explanation = "Ninguna norma candidata del BOE trata, por su título, de lo prometido."
    evidence = [{k: c[k] for k in ("source", "id", "label", "url", "period", "rank")} for c in cited]
    return {"status": status, "explanation": explanation, "evidence": evidence}


def ai_step(session: Session, ai, max_calls: int, batch_size: int, govs=None) -> dict:
    """Paso 3: propuestas de la IA por lotes, pendientes de revision. Tope de llamadas por ciclo."""
    summary = {"calls": 0, "proposals": 0, "input_tokens": 0, "output_tokens": 0, "errors": 0}
    queue = ai_queue(session, govs)
    for start in range(0, len(queue), batch_size):
        if summary["calls"] >= max_calls:
            break
        batch = queue[start : start + batch_size]
        g = government_of(batch[0][0], govs)
        batch = [x for x in batch if government_of(x[0], govs) == g]
        summary["calls"] += 1
        try:
            result = ai.structured(AI_SYSTEM, ai_prompt(batch, g), AI_SCHEMA)
        except Exception as exc:  # sin credito, caida o respuesta inutil: nada se guarda y se para el ciclo
            log.warning("cumplimiento con IA: lote descartado, se para hasta el siguiente ciclo (%s)", exc)
            summary["errors"] += 1
            summary["last_error"] = str(exc)[:200]
            break
        for k in ("input_tokens", "output_tokens"):
            summary[k] += result.usage.get(k) or 0
        answers = {it.get("id"): it for it in result.data.get("items") or [] if isinstance(it, dict)}
        for p, cands in batch:
            item = answers.get(p.id)
            if item is None:
                continue  # sin respuesta para esta promesa: vuelve a la cola
            session.add(PromiseCheck(promise_id=p.id, method=PENDING, **validate(item, cands)))
            summary["proposals"] += 1
    return summary


def review(session: Session, check_id: int, approve: bool, user: str) -> PromiseCheck:
    """Una persona aprueba (se publica como asistida por IA) o rechaza una propuesta pendiente."""
    chk = session.get(PromiseCheck, check_id)
    if chk is None or chk.method != PENDING:
        raise ValueError("solo se revisa una propuesta pendiente")
    chk.method = METHOD_AI if approve else REJECTED
    chk.explanation += f" [Revisado por {user} el {datetime.now(UTC):%d/%m/%Y}]"
    session.flush()
    return chk


def pending(session: Session, limit: int = 50) -> list[tuple[PromiseCheck, Promise]]:
    return list(
        session.execute(
            select(PromiseCheck, Promise)
            .join(Promise, PromiseCheck.promise_id == Promise.id)
            .where(PromiseCheck.method == PENDING)
            .order_by(PromiseCheck.id)
            .limit(limit)
        ).all()
    )


def run(
    session: Session, settings, ai=None, today: date | None = None, search=boe.search, pause: float = 0.3
) -> dict:
    """Paso del worker: reglas siempre; IA solo si hay clave y solo con lo que el codigo no decidio."""
    today = today or datetime.now(UTC).date()
    per_run = settings.promises_check_per_run
    summary = {"rules": rules_step(session, per_run, today, search=search, pause=pause)}
    session.flush()
    if ai is not None and settings.promises_ai_max_calls > 0:
        summary["ai"] = ai_step(session, ai, settings.promises_ai_max_calls, settings.promises_ai_batch)
    log.info("cumplimiento de promesas: %s", summary)
    return summary
