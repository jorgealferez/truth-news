"""Extraccion de afirmaciones numericas sobre indicadores conocidos (registry/indicators.yaml).

Conservadora a proposito: solo extrae niveles ("la tasa de paro es del 10,5 %"), no variaciones en
puntos, ni datos regionales, ni de colectivos (jovenes, mujeres...), ni referidos a anos pasados.
Lo que no se puede comprobar con una serie nacional no se extrae: mejor callar que acusar.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache

import yaml

from truthnews.classify import normalize
from truthnews.registry import REGISTRY_DIR, countries

_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")
_PCT = r"(?P<num>\d{1,3}(?:[.,]\d{1,2})?)\s*(?:%|por ciento|percent|por cento)"
_ABS = re.compile(r"(\d{1,3}(?:[.,]\d{1,3})?)\s*(millones|million|milhoes|milhões)")
_YEAR = re.compile(r"\b(19[5-9]\d|20[0-4]\d)\b")
_UP = re.compile(
    r"\b(sube|subio|aumenta|aumento|crece|crecio|repunta|repunto|se dispara"
    r"|rises|rose|increases|grew|sobe|subiu)\b"
)
_DOWN = re.compile(
    r"\b(baja|bajo|cae|cayo|desciende|descendio|se reduce|se modera"
    r"|falls|fell|drops|decreases|desce|caiu)\b"
)
_SUBGROUP = re.compile(
    r"\b(juvenil|jovenes|menores de|mujeres|hombres|parados de larga|youth|women|men|jovens)\b"
)
_CHANGE = re.compile(r"\b(puntos|points|pontos|decimas)\b")
# Pasado, previsiones y condicionales: no se comparan con el ultimo dato publicado.
_NOT_CURRENT = re.compile(
    r"\b(pasado ano|ano pasado|el pasado ejercicio|ano anterior|previsto|prevision|previsiones|preve|preven"
    r"|avanzara|crecera|subira|bajara|se situara|estima|estimacion|proyecta|podria|podra|objetivo de"
    r"|last year|forecast|expected|will|projected|previsao)\b"
)
# Construccion explicita indicador -> (verbo) -> conector -> cifra: "la inflacion sube al 4,9 %".
_VERBS = (
    r"(?:se\s+situa|se\s+situo|se\s+coloca|se\s+coloco|alcanza|alcanzo|sube|subio|baja|bajo|cae|cayo"
    r"|repunta|repunto|se\s+modera|se\s+modero|escala|escalo|llega|llego|queda|quedo|cierra|cerro|marca|marco"
    r"|crece|crecio|avanza|avanzo|es|fue|esta|estaba|rises\s+to|rose\s+to|falls\s+to|fell\s+to|is|was"
    r"|stands\s+at|stood\s+at|sobe|subiu|desce|desceu|fica|ficou)"
)
_CONNECT = r"(?:en\s+el|en\s+un|al|del|de\s+un|hasta\s+el|hasta\s+un|un|at|to|of|no|para\s+os|em)"


@lru_cache(maxsize=1)
def indicators() -> dict:
    data = yaml.safe_load((REGISTRY_DIR / "indicators.yaml").read_text(encoding="utf-8"))
    return data


@lru_cache(maxsize=1)
def world_countries() -> dict[str, list[str]]:
    data = yaml.safe_load((REGISTRY_DIR / "world.yaml").read_text(encoding="utf-8"))
    return {iso: [normalize(n) for n in names] for iso, names in data.items()}


@lru_cache(maxsize=1)
def _region_names() -> list[str]:
    names = []
    for c in countries().values():
        names += [normalize(n) for n in c.get("regions", {}).values()]
    names += ["andalucia", "cataluna", "catalunya", "euskadi", "galicia", "madrid", "valencia"]
    return sorted(set(names), key=len, reverse=True)


_MONTHS = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
_MONTH_RE = re.compile(r"\b(" + "|".join(_MONTHS) + r")\b(?:\s+(?:de|del)\s+(\d{4}))?")
_QUARTER_RE = re.compile(
    r"\b(primer|segundo|tercer|cuarto|first|second|third|fourth)\s+(?:trimestre|quarter)(?:\s+(?:de|del|of)\s+(\d{4}))?"
)
_QUARTERS = {
    "primer": 1,
    "first": 1,
    "segundo": 2,
    "second": 2,
    "tercer": 3,
    "third": 3,
    "cuarto": 4,
    "fourth": 4,
}


def period_of(sentence_n: str, published_year: int, published_month: int = 12) -> str | None:
    """Periodo citado en la frase ('2026-08', '2026-Q2') o None si no cita ninguno.

    Sin ano explicito, un mes posterior al de publicacion se entiende del ano anterior.
    """
    m = _MONTH_RE.search(sentence_n)
    # "mayo" solo cuenta como mes con ano o tras "en" (tambien es sustantivo).
    if m and (m.group(1) != "mayo" or m.group(2) or re.search(r"\ben\s+mayo\b", sentence_n)):
        month = _MONTHS[m.group(1)]
        year = int(m.group(2)) if m.group(2) else published_year - (1 if month > published_month else 0)
        return f"{year}-{month:02d}"
    q = _QUARTER_RE.search(sentence_n)
    if q:
        quarter = _QUARTERS[q.group(1)]
        year = (
            int(q.group(2))
            if q.group(2)
            else published_year - (1 if quarter * 3 > published_month + 2 else 0)
        )
        return f"{year}-Q{quarter}"
    return None


@dataclass
class ClaimCandidate:
    text: str
    indicator: str
    geo: str
    value: float
    unit: str
    direction: str | None
    period: str | None = None  # periodo citado: se compara con el dato de ese periodo, no con el ultimo


def _number(raw: str) -> float:
    raw = raw.replace(",", ".")
    if raw.count(".") == 1 and len(raw.split(".")[1]) == 3:  # 1.234 (millares) en abs
        raw = raw.replace(".", "")
    return float(raw)


def _word_in(needle: str, haystack: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None


def _geo(sentence_n: str, default: str, explicit_only: bool = False) -> str | None:
    named = {
        iso
        for iso, names in indicators()["geo_names"].items()
        if any(_word_in(normalize(n), sentence_n) for n in names)
    }
    if len(named) > 1:
        return None  # varios territorios en la frase: no se adivina a cual se refiere la cifra
    others = {
        iso
        for iso, names in world_countries().items()
        if iso not in named and any(_word_in(n, sentence_n) for n in names)
    }
    if others:
        return None  # nombra un pais del que no tenemos serie (o ademas de otro): no se atribuye
    if named:
        return named.pop()
    if explicit_only:
        return None
    if any(_word_in(normalize(m), sentence_n) for m in indicators()["foreign_markers"]):
        return None  # habla de otro pais sin nombrarlo: no se atribuye al del medio
    return default if default not in ("XX", "") else None


def sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENTENCE.split(text or "") if 20 <= len(s.strip()) <= 600]


def extract(
    text: str, language: str, default_geo: str, published_year: int, published_month: int = 12
) -> list[ClaimCandidate]:
    out: list[ClaimCandidate] = []
    seen: set[tuple] = set()
    for sentence in sentences(text):
        sn = normalize(sentence)
        if _SUBGROUP.search(sn) or _CHANGE.search(sn) or _NOT_CURRENT.search(sn):
            continue
        years = {int(y) for y in _YEAR.findall(sn)}
        if any(y < published_year - 1 for y in years):
            continue  # habla de un ano pasado: no se compara con el ultimo dato
        if any(re.search(r"(?<!\w)" + re.escape(r) + r"(?!\w)", sn) for r in _region_names()):
            continue  # dato regional: no hay serie nacional con la que compararlo
        for key, ind in indicators().items():
            if key in ("geo_names", "eu_geos", "foreign_markers"):
                continue
            requires = ind.get("requires", [])
            if requires and not any(_word_in(normalize(r), sn) for r in requires):
                continue
            pats = ind["patterns"].get(language) or ind["patterns"].get("es", [])
            value, verb = None, ""
            for p in pats:
                pn = re.escape(normalize(p))
                if ind["unit"] == "pct":
                    link = rf"(?:(?P<verb>{_VERBS})\s+(?:{_CONNECT}\s+)?|{_CONNECT}\s+)"
                    # Periodo entre indicador y verbo: "la inflacion de agosto se situo en el 4,3 %".
                    gap = (
                        rf"(?:(?:de|en|del mes de|in)\s+(?:{'|'.join(_MONTHS)})(?:\s+(?:de\s+)?\d{{4}})?\s+)?"
                    )
                    rx = rf"(?<!\w){pn}(?!\w)\s+{gap}{link}{_PCT}"
                    m = re.search(rx, sn)
                    if m and "del pib" not in sn[m.end() : m.end() + 8]:
                        value = _number(m.group("num"))
                        verb = m.group("verb") or ""
                else:
                    m = re.search(rf"{_ABS.pattern}\s+(?:de\s+)?{pn}", sn)
                    if m:
                        value = _number(m.group(1)) * 1_000_000
                if value is not None:
                    break
            if value is None:
                continue
            geo = _geo(sn, default_geo, explicit_only=ind.get("requires_explicit_geo", False))
            if geo is None:
                continue
            direction = "sube" if _UP.search(verb) else "baja" if _DOWN.search(verb) else None
            if not ind.get("directional", True):
                direction = None
            k = (key, geo, value)
            if k in seen:
                continue
            seen.add(k)
            period = period_of(sn, published_year, published_month)
            out.append(ClaimCandidate(sentence[:600], key, geo, value, ind["unit"], direction, period))
    return out


def indicator_name(key: str, lang: str = "es") -> str:
    ind = indicators().get(key, {})
    return ind.get("name", {}).get(lang) or ind.get("name", {}).get("es", key)
