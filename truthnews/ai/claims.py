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
from datetime import datetime
from functools import lru_cache

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
from truthnews.analysis.pipeline import _aware, article_text, save_claim
from truthnews.analysis.verify import Verifier, applicable
from truthnews.classify import normalize
from truthnews.models import Article, Claim

log = logging.getLogger(__name__)
BATCH = 40  # frases por llamada
_HAS_FIGURE = re.compile(
    r"\d\s*(?:%|por ciento|percent|por cento)|\d\s*(?:millones|million|milh)|\d{1,3}(?:\.\d{3}){2,}"
)

SYSTEM = """Eres el extractor de afirmaciones comprobables de nosmienten.com, un verificador neutral.
Recibes frases de noticias, cada una con su id, el pais del medio y la fecha de publicacion. Para cada
frase decide si contiene una afirmacion que se pueda comprobar con UNA de las series oficiales de la
lista (indicador y territorio) y, si es asi, extraela tal cual la dice el texto. No juzgas si es verdad:
eso lo hace despues el codigo con el dato oficial.

Reglas (mejor descartar que atribuir mal):
- Solo niveles del indicador general ("el paro es del 10,5 %"), no variaciones en puntos, ni datos de
  colectivos (jovenes, mujeres, un sector), ni regionales o de ciudades, ni previsiones o condicionales.
- valor: la cifra exacta escrita en la frase, en la unidad del indicador (porcentaje como 10.5;
  cantidades en unidades: "48,6 millones" es 48600000).
- territorio: el codigo del pais o zona al que se refiere la cifra. Si la frase no nombra ninguno, es el
  pais del medio. Si no puedes saber con seguridad a que territorio corresponde, comprobable=false.
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
    geos = list(indicators()["geo_names"])
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
    return "\n".join(lines)


def _source_geos(source: dict) -> list[str]:
    all_geos = list(indicators()["geo_names"])
    return [g for g in all_geos if applicable(source, g)]


def _has_series(indicator: str, geo: str) -> bool:
    return any(applicable(s, geo) for s in indicators()[indicator]["sources"])


def run(
    session: Session,
    ai: AIClient,
    since: datetime,
    verifier: Verifier | None = None,
    max_calls: int = 3,
) -> dict:
    """Propone afirmaciones de los articulos ingeridos desde `since`, las valida y las juzga."""
    verifier = verifier or Verifier()
    arts = list(
        session.scalars(
            select(Article)
            .options(joinedload(Article.outlet))
            .where(Article.fetched_at >= since)
            .order_by(Article.published_at.desc())
        )
    )
    known = {
        (aid, text)
        for aid, text in session.execute(
            select(Claim.article_id, Claim.text).where(Claim.article_id.in_([a.id for a in arts] or [-1]))
        )
    }
    items: list[tuple[Article, str]] = []
    for a in arts:
        for s in candidate_sentences(article_text(a)):
            if (a.id, s[:600]) not in known:
                items.append((a, s))
    stats: Counter = Counter(frases_candidatas=len(items))
    verdicts: Counter = Counter()
    rejected: Counter = Counter()
    usage: Counter = Counter()
    for start in range(0, min(len(items), BATCH * max_calls), BATCH):
        batch = items[start : start + BATCH]
        payload = [
            {"id": i, "pais_del_medio": a.country, "fecha": f"{_aware(a.published_at):%Y-%m-%d}", "frase": s}
            for i, (a, s) in enumerate(batch)
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
            break
        stats["llamadas"] += 1
        stats["frases_enviadas"] += len(batch)
        for k, v in (res.usage or {}).items():
            usage[k] += v or 0
        for p in res.data.get("afirmaciones", []):
            i = p.get("id")
            if not isinstance(i, int) or not 0 <= i < len(batch) or not p.get("comprobable"):
                continue
            stats["propuestas"] += 1
            a, sentence = batch[i]
            pub = _aware(a.published_at)
            cand = check_proposal(
                sentence,
                article_text(a),
                p.get("indicador", ""),
                p.get("territorio", ""),
                float(p.get("valor", 0)),
                p.get("periodo") or None,
                p.get("sentido"),
                a.country,
                pub.year,
                pub.month,
            )
            if isinstance(cand, ClaimCandidate) and not _has_series(cand.indicator, cand.geo):
                cand = "sin serie oficial para ese territorio"
            if not isinstance(cand, ClaimCandidate):
                rejected[cand] += 1
                continue
            verdict = save_claim(session, a, cand, verifier, extractor="ia")
            if verdict is None:
                continue
            stats["aceptadas"] += 1
            verdicts[verdict] += 1
        session.commit()  # cada lote queda guardado aunque el ciclo se corte
    out = {**stats, "veredictos": dict(verdicts), "rechazos": dict(rejected), "uso": dict(usage)}
    out["juzgadas"] = sum(n for v, n in verdicts.items() if v != "sin-datos")
    log.info("afirmaciones con IA: %s", out)
    return out
