"""Extraccion de afirmaciones comprobables con IA (ADR 0007, 0019).

La IA lee frases con cifra y propone indicador, territorio, periodo y valor. El codigo valida cada
propuesta con reglas deterministas (`check_proposal`) y el veredicto lo sigue dando el codigo contra la
serie oficial. Lo que la IA no puede atribuir con seguridad, o el codigo no confirma, no se juzga.
"""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from truthnews.ai.client import AIClient, AIError
from truthnews.analysis.claims import (
    ClaimCandidate,
    check_proposal,
    indicator_keys,
    indicator_name,
    indicators,
    sentences,
)
from truthnews.analysis.pipeline import _aware, article_text, default_geo_of, save_claim
from truthnews.analysis.verify import Verifier, applicable
from truthnews.classify import normalize
from truthnews.models import Article, Claim

log = logging.getLogger(__name__)
BATCH = 40  # frases por llamada
_HAS_FIGURE = re.compile(
    r"\d\s*(?:%|por ciento|percent|por cento)|\d\s*(?:millones|million|milh)|\d{1,3}(?:\.\d{3}){2,}"
)

SYSTEM = """Eres el extractor de afirmaciones comprobables de nosmienten.com, un verificador neutral.
Recibes frases de noticias, cada una con su id, el pais por defecto y la fecha de publicacion. Para cada
frase decide si contiene una afirmacion que se pueda comprobar con UNA de las series oficiales de la
lista (indicador y territorio) y, si es asi, extraela tal cual la dice el texto. No juzgas si es verdad:
eso lo hace despues el codigo con el dato oficial.

Reglas (mejor descartar que atribuir mal):
- Solo niveles del indicador general ("el paro es del 10,5 %"), no variaciones ("baja un 2 %", "0,3
  puntos"), ni datos de colectivos (jovenes, mujeres, un sector), ni de ciudades, ni previsiones o
  condicionales. Datos de una comunidad autonoma solo si el indicador tiene serie para ella (codigo ES-XX).
- valor: la cifra exacta escrita en la frase, en la unidad del indicador (porcentaje como 10.5;
  cantidades en unidades: "48,6 millones" es 48600000).
- territorio: el codigo del pais o zona al que se refiere la cifra. Si la frase no nombra ninguno, es el
  pais_por_defecto; si este es "XX" (noticia de otro pais), la frase tiene que nombrar el territorio o
  comprobable=false. Si no puedes saber con seguridad a que territorio corresponde, comprobable=false.
- periodo: "AAAA-MM" si la frase cita un mes, "AAAA-QN" si cita un trimestre, "AAAA" si cita un ano, o
  "" si habla del dato actual sin citar periodo. No lo deduzcas de la fecha si la frase no lo dice.
- sentido: "sube" o "baja" solo si la frase dice que el indicador sube o baja; si no, "ninguno".
- Mismo criterio para todos los medios, partidos y gobiernos. Ante la duda, comprobable=false con motivo.
Devuelve una entrada por frase recibida, con su mismo id."""


@lru_cache(maxsize=1)
def _keywords() -> list[str]:
    words = {
        normalize(p) for k in indicator_keys() for ps in indicators()[k]["patterns"].values() for p in ps
    }
    return sorted(words, key=len, reverse=True)


def candidate_sentences(text: str) -> list[str]:
    """Frases con una cifra con unidad y una palabra de indicador: las unicas que merece la pena enviar."""
    out = []
    for s in sentences(text):
        sn = normalize(s)
        if _HAS_FIGURE.search(sn) and any(
            re.search(r"(?<!\w)" + re.escape(k) + r"(?!\w)", sn) for k in _keywords()
        ):
            out.append(s)
    return out


def claims_schema() -> dict:
    geos = list(indicators()["geo_names"]) + list(indicators().get("region_names", {}))
    item = {
        "type": "object",
        "properties": {
            "id": {"type": "integer"},
            "comprobable": {"type": "boolean"},
            "indicador": {"type": "string", "enum": [*indicator_keys(), "ninguno"]},
            "territorio": {"type": "string", "enum": [*geos, "ninguno"]},
            "periodo": {"type": "string"},
            "valor": {"type": "number"},
            "sentido": {"type": "string", "enum": ["sube", "baja", "ninguno"]},
            "motivo": {"type": "string"},
        },
        "required": ["id", "comprobable", "indicador", "territorio", "periodo", "valor", "sentido", "motivo"],
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"afirmaciones": {"type": "array", "items": item}},
        "required": ["afirmaciones"],
        "additionalProperties": False,
    }


def _catalog() -> str:
    lines = []
    for k in indicator_keys():
        ind = indicators()[k]
        geos = sorted({g for s in ind["sources"] for g in _source_geos(s)})
        unit = "porcentaje" if ind["unit"] == "pct" else "cantidad"
        lines.append(f"- {k}: {indicator_name(k)} ({unit}); territorios: {', '.join(geos)}")
    regions = indicators().get("region_names", {})
    if regions:
        lines.append("Comunidades autonomas: " + "; ".join(f"{k} {v[0]}" for k, v in regions.items()))
    return "\n".join(lines)


def _source_geos(source: dict) -> list[str]:
    all_geos = list(indicators()["geo_names"]) + list(indicators().get("region_names", {}))
    return [g for g in all_geos if applicable(source, g)]


def _has_series(indicator: str, geo: str) -> bool:
    return any(applicable(s, geo) for s in indicators()[indicator]["sources"])


@dataclass(frozen=True)
class Item:
    """Una frase que se propone a la IA, con el texto del que sale (para comprobar que esta literal)."""

    sentence: str
    text: str
    default_geo: str  # "XX" si no se puede suponer el pais
    published: datetime
    ref: Any = None  # lo que el llamador necesite para guardar (un Article, una declaracion...)


def propose_batch(ai: AIClient, batch: list[Item], stats: Counter, rejected: Counter, usage: Counter):
    """Una llamada: propuestas de la IA ya validadas por las reglas. None si la IA no esta disponible."""
    payload = [
        {
            "id": i,
            "pais_por_defecto": it.default_geo,
            "fecha": f"{_aware(it.published):%Y-%m-%d}",
            "frase": it.sentence,
        }
        for i, it in enumerate(batch)
    ]
    user = (
        "Series oficiales disponibles:\n"
        + _catalog()
        + "\n\nFrases:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    try:
        res = ai.structured(SYSTEM, user, claims_schema())
    except AIError as exc:
        log.warning("extraccion con IA no disponible: %s", exc)
        stats["errores"] += 1
        return None
    stats["llamadas"] += 1
    stats["frases_enviadas"] += len(batch)
    for k, v in (res.usage or {}).items():
        usage[k] += v or 0
    accepted: list[tuple[Item, ClaimCandidate]] = []
    for p in res.data.get("afirmaciones", []):
        i = p.get("id")
        if not isinstance(i, int) or not 0 <= i < len(batch) or not p.get("comprobable"):
            continue
        stats["propuestas"] += 1
        it = batch[i]
        pub = _aware(it.published)
        cand = check_proposal(
            it.sentence,
            it.text,
            p.get("indicador", ""),
            p.get("territorio", ""),
            float(p.get("valor", 0)),
            p.get("periodo") or None,
            p.get("sentido"),
            it.default_geo,
            pub.year,
            pub.month,
        )
        if isinstance(cand, ClaimCandidate) and not _has_series(cand.indicator, cand.geo):
            cand = "sin serie oficial para ese territorio"
        if not isinstance(cand, ClaimCandidate):
            rejected[cand] += 1
            continue
        accepted.append((it, cand))
    return accepted


def propose(
    ai: AIClient, items: list[Item], max_calls: int = 3
) -> tuple[list[tuple[Item, ClaimCandidate]], dict]:
    """Punto de entrada sin base de datos: candidatos validados (el veredicto lo da verify.py)."""
    stats: Counter = Counter(frases_candidatas=len(items))
    rejected: Counter = Counter()
    usage: Counter = Counter()
    out: list[tuple[Item, ClaimCandidate]] = []
    for start in range(0, min(len(items), BATCH * max_calls), BATCH):
        got = propose_batch(ai, items[start : start + BATCH], stats, rejected, usage)
        if got is None:
            break
        out += got
    return out, {**stats, "rechazos": dict(rejected), "uso": dict(usage)}


def run(
    session: Session,
    ai: AIClient,
    since: datetime,
    verifier: Verifier | None = None,
    max_calls: int = 3,
    only: Callable[[Article], bool] | None = None,
) -> dict:
    """Propone afirmaciones de los articulos ingeridos desde `since` (con `only`, solo los que pasen el
    filtro, p. ej. los del foco, ADR 0056), las valida y las juzga."""
    verifier = verifier or Verifier()
    arts = list(
        session.scalars(
            select(Article)
            .options(joinedload(Article.outlet))
            .where(Article.fetched_at >= since, Article.origin == "rss")  # sin archivo (ADR 0028)
            .order_by(Article.published_at.desc())
        )
    )
    if only is not None:
        arts = [a for a in arts if only(a)]
    known = {
        (aid, text)
        for aid, text in session.execute(
            select(Claim.article_id, Claim.text).where(Claim.article_id.in_([a.id for a in arts] or [-1]))
        )
    }
    items: list[Item] = []
    for a in arts:
        text = article_text(a)
        for s in candidate_sentences(text):
            if (a.id, s[:600]) not in known:
                items.append(Item(s, text, default_geo_of(a), a.published_at, a))
    stats: Counter = Counter(frases_candidatas=len(items))
    verdicts: Counter = Counter()
    rejected: Counter = Counter()
    usage: Counter = Counter()
    for start in range(0, min(len(items), BATCH * max_calls), BATCH):
        accepted = propose_batch(ai, items[start : start + BATCH], stats, rejected, usage)
        if accepted is None:
            break
        for it, cand in accepted:
            verdict = save_claim(session, it.ref, cand, verifier, extractor="ia")
            if verdict is None:
                continue
            stats["aceptadas"] += 1
            verdicts[verdict] += 1
        session.commit()  # cada lote queda guardado aunque el ciclo se corte
    out = {**stats, "veredictos": dict(verdicts), "rechazos": dict(rejected), "uso": dict(usage)}
    out["juzgadas"] = sum(n for v, n in verdicts.items() if v != "sin-datos")
    log.info("afirmaciones con IA: %s", out)
    return out
