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

META_KEYS = ("geo_names", "eu_geos", "foreign_markers", "region_names")
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
# "El paro baja un 2 %": es una variacion del indicador, no su nivel. Solo vale como nivel en los
# indicadores que ya son una tasa de variacion (crecimiento del PIB, variacion del precio de la vivienda).
_VARIATION = re.compile(
    r"\b(sube|subio|subido|baja|bajo|bajado|cae|cayo|caido|crece|crecio|crecido|aumenta|aumento|aumentado"
    r"|desciende|descendio|descendido|se reduce|se redujo|reducido|repunta|repunto|se dispara|se disparo"
    r"|retrocede|retrocedio|mejora|mejoro|empeora|empeoro|avanza|avanzo|subida|bajada|caida|descenso"
    r"|incremento|reduccion|rises|rose|falls|fell|increases|decreases|grew|sobe|subiu|desce|caiu"
    # Efecto de un indicador sobre otra cosa (caso real, El Debate 19/10/2026: "la inflacion le resta un
    # 3,1 %" a los ingresos): tampoco es el nivel del indicador.
    r"|resta|restan|resto|restado|quita|quitan|quito|recorta|recortan|reduce|reducen|redujo|merma|mermo"
    r"|erosiona|erosionan|descuenta|lastra|lastro|se come|se comen|se comio|suma|suman|sumo|anade|anadio"
    r"|aporta|aportan|aporto)"
    r"\s+(?:(?:de|en|del|hasta)\s+)?(?:un|una|um|uma|by)\s*$"
)


def is_variation(before: str) -> bool:
    """Si el texto normalizado justo antes de la cifra la presenta como una variacion ("baja un")."""
    return _VARIATION.search(before[-60:]) is not None


# Pasado, previsiones y condicionales: no se comparan con el ultimo dato publicado.
_NOT_CURRENT = re.compile(
    r"\b(pasado ano|ano pasado|el pasado ejercicio|ano anterior|previsto|prevision|previsiones|preve|preven"
    r"|avanzara|crecera|subira|bajara|se situara|estima|estimacion|proyecta|podria|podra|objetivo de"
    r"|last year|forecast|expected|will|projected|previsao"
    # Caso real (La Informacion, 19/10/2026): "eleva su expectativa de inflacion al 3,7 % en 2026" es una
    # prevision, no el dato publicado.
    r"|expectativa|expectativas|eleva su|elevan su|rebaja su|rebajan su|revisa al alza|revisa a la baja"
    r"|pronostico|pronostica|pronostican|proyeccion|proyecciones|anticipa|calcula que|espera que|esperan que"
    r"|outlook|projection|estimate|estimates|expects"
    r")\b"
)
# Construccion explicita indicador -> (verbo) -> conector -> cifra: "la inflacion sube al 4,9 %".
_VERBS = (
    r"(?:se\s+situa|se\s+situo|se\s+coloca|se\s+coloco|alcanza|alcanzo|sube|subio|baja|bajo|cae|cayo"
    r"|repunta|repunto|se\s+modera|se\s+modero|escala|escalo|llega|llego|queda|quedo|cierra|cerro|marca|marco"
    r"|crece|crecio|avanza|avanzo|es|fue|esta|estaba|rises\s+to|rose\s+to|falls\s+to|fell\s+to|is|was"
    r"|alcanzan|alcanzaron|se\s+situan|se\s+situaron|son|fueron|suben|subieron|bajan|bajaron|caen|cayeron"
    r"|stands\s+at|stood\s+at|sobe|subiu|desce|desceu|fica|ficou)"
)
_CONNECT = r"(?:en\s+el|en\s+un|al|del|de\s+un|hasta\s+el|hasta\s+un|el|un|at|to|of|no|para\s+os|em)"


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


@lru_cache(maxsize=1)
def _territory_gap() -> str:
    """Territorio entre indicador y verbo: "el paro en Andalucia se situa en el 14 %"."""
    names = [normalize(n) for ns in indicators()["geo_names"].values() for n in ns]
    names += [normalize(n) for ns in indicators().get("region_names", {}).values() for n in ns]
    alt = "|".join(re.escape(n) for n in sorted(set(names), key=len, reverse=True))
    return rf"(?:(?:en|de)\s+(?:la\s+|el\s+)?(?:{alt})\s+)?"


def _requirements_met(ind: dict, sn: str) -> bool:
    requires = ind.get("requires", [])
    if not requires or any(_word_in(normalize(r), sn) for r in requires):
        return True
    return bool(ind.get("requires_year_ok") and _YEAR.search(sn))


def regions_in(sn: str) -> tuple[dict[str, list[int]], bool]:
    """Comunidades nombradas sin ambiguedad (codigo -> posiciones) y si queda otro nombre regional dudoso."""
    found: dict[str, list[int]] = {}
    masked = sn
    for code, names in indicators().get("region_names", {}).items():
        for n in names:
            for m in re.finditer(r"(?<!\w)" + re.escape(normalize(n)) + r"(?!\w)", sn):
                found.setdefault(code, []).append(m.start())
                masked = masked[: m.start()] + " " * (m.end() - m.start()) + masked[m.end() :]
    leftover = any(_word_in(r, masked) for r in _region_names())
    return found, leftover


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
        past = any(y < published_year - 1 for y in years)  # habla de un ano pasado
        regions, leftover = regions_in(sn)
        if leftover or len(regions) > 1:
            continue  # nombre regional dudoso (ciudad o comunidad) o varias comunidades: no se atribuye
        for key, ind in indicators().items():
            if key in META_KEYS:
                continue
            if past and not (ind.get("annual") and len(years) == 1):
                continue  # un ano pasado solo se compara en una serie anual con ese ano citado
            if not _requirements_met(ind, sn):
                continue
            if any(_word_in(normalize(x), sn) for x in ind.get("excludes", [])):
                continue  # otro indicador parecido (p. ej. pobreza o exclusion frente a riesgo de pobreza)
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
                    rx = rf"(?<!\w){pn}(?!\w)\s+{_territory_gap()}{gap}{link}{_PCT}"
                    m = re.search(rx, sn)
                    if m and not ind.get("change_is_level") and is_variation(sn[: m.start("num")]):
                        m = None  # "baja un 2 %": variacion, no nivel
                    if m and (ind.get("of_gdp") or "del pib" not in sn[m.end() : m.end() + 8]):
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
            if regions:
                if not ind.get("regional") or _geo(sn, "", explicit_only=True) or _named_positions(sn):
                    continue  # sin serie regional, o la frase nombra tambien un pais
                geo = next(iter(regions))
            else:
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
            if period is None and not ind.get("annual") and any(y >= published_year for y in years):
                continue  # cifra del ano en curso o futuro: no es el ultimo dato mensual o trimestral
            if period is None and ind.get("annual") and len(years) == 1:
                period = str(next(iter(years)))  # "crecio un 2,6 % en 2025": se compara con 2025
            out.append(ClaimCandidate(sentence[:600], key, geo, value, ind["unit"], direction, period))
    return out


def indicator_name(key: str, lang: str = "es") -> str:
    ind = indicators().get(key, {})
    return ind.get("name", {}).get(lang) or ind.get("name", {}).get("es", key)


# --- Propuestas de la IA (ADR 0019): la IA propone, estas reglas deciden si es atribuible -------------
_FORECAST = re.compile(
    r"\b(previsto|prevision|previsiones|preve|preven|avanzara|crecera|subira|bajara|se situara|estima"
    r"|estimacion|proyecta|podria|podra|objetivo de|forecast|expected|will|projected|previsao"
    # Caso real (La Informacion, 19/10/2026): "eleva su expectativa de inflacion al 3,7 % en 2026" es una
    # prevision, no el dato publicado.
    r"|expectativa|expectativas|eleva su|elevan su|rebaja su|rebajan su|revisa al alza|revisa a la baja"
    r"|pronostico|pronostica|pronostican|proyeccion|proyecciones|anticipa|calcula que|espera que|esperan que"
    r"|outlook|projection|estimate|estimates|expects"
    r")\b"
)
_ANY_NUM = re.compile(r"\d+(?:[.,]\d+)*")
_PERIOD = re.compile(r"^(\d{4})(?:-(0[1-9]|1[0-2])|-Q([1-4]))?$")


def indicator_keys() -> list[str]:
    return [k for k in indicators() if k not in META_KEYS]


def _number_positions(sn: str, unit: str, value: float) -> list[int]:
    """Posiciones en la frase normalizada donde aparece la cifra propuesta con su unidad."""
    out = []
    if unit == "pct":
        for m in re.finditer(_PCT, sn):
            if abs(_number(m.group("num")) - value) < 1e-9:
                out.append(m.start())
        return out
    for m in _ABS.finditer(sn):
        if abs(_number(m.group(1)) * 1_000_000 - value) < 0.5:
            out.append(m.start())
    for m in _ANY_NUM.finditer(sn):  # cifra completa: "48.619.695 habitantes"
        raw = m.group(0)
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", raw) and abs(float(re.sub(r"[.,]", "", raw)) - value) < 0.5:
            out.append(m.start())
    return out


def _named_positions(sn: str) -> dict[str, list[int]]:
    found: dict[str, list[int]] = {}
    for iso, names in indicators()["geo_names"].items():
        for n in names:
            for m in re.finditer(r"(?<!\w)" + re.escape(normalize(n)) + r"(?!\w)", sn):
                found.setdefault(iso, []).append(m.start())
    return found


def check_proposal(
    sentence: str,
    article_text: str,
    indicator: str,
    geo: str,
    value: float,
    period: str | None,
    direction: str | None,
    default_geo: str,
    published_year: int,
    published_month: int = 12,
) -> ClaimCandidate | str:
    """Valida una afirmacion propuesta por la IA. Devuelve el candidato o el motivo del rechazo.

    Mejor callar que acusar: se rechaza todo lo que no se pueda atribuir con reglas deterministas.
    """
    sentence = sentence.strip()
    if sentence not in sentences(article_text):
        return "la frase no esta literalmente en el articulo"
    if indicator not in indicator_keys():
        return "indicador desconocido"
    ind = indicators()[indicator]
    sn = normalize(sentence)
    pats = {normalize(p) for ps in ind["patterns"].values() for p in ps}
    if not any(_word_in(p, sn) for p in pats):
        return "la frase no nombra el indicador"
    if not _requirements_met(ind, sn):
        return "falta el contexto que exige el indicador"
    if any(_word_in(normalize(x), sn) for x in ind.get("excludes", [])):
        return "la frase habla de otro indicador parecido"
    if _SUBGROUP.search(sn):
        return "dato de un colectivo: no hay serie general con la que compararlo"
    if _CHANGE.search(sn):
        return "variacion en puntos: no es un nivel"
    if _FORECAST.search(sn):
        return "prevision o condicional"
    regions, leftover = regions_in(sn)
    if leftover:
        return "nombre regional dudoso (ciudad o comunidad): no se atribuye"
    if regions and not ind.get("regional"):
        return "dato regional: no hay serie regional con la que compararlo"
    positions = _number_positions(sn, ind["unit"], value)
    if ind["unit"] == "pct" and not ind.get("change_is_level"):
        positions = [p for p in positions if not is_variation(sn[:p])]
        if not positions:
            return "la cifra es una variacion del indicador, no su nivel"
    if ind["unit"] == "pct" and not ind.get("of_gdp"):
        positions = [p for p in positions if "del pib" not in sn[p : p + 20]]  # "% del PIB" es otro dato
    if not positions:
        return "la cifra no aparece en la frase con su unidad"
    # Periodo: el que fijan las reglas manda; un ano suelto solo si esta escrito en la frase.
    ruled = period_of(sn, published_year, published_month)
    if period in ("", None):
        period = None
    elif not _PERIOD.match(period):
        return "periodo con formato invalido"
    if ruled and period not in (None, ruled):
        return "el periodo no cuadra con la frase"
    period = ruled or period
    if not ruled and period and (len(period) != 4 or period not in sn):
        return "periodo no escrito en la frase"
    years = {int(y) for y in _YEAR.findall(sn)}
    if not period and not ind.get("annual") and any(y >= published_year for y in years):
        return "cifra del ano en curso o futuro: no es el ultimo dato mensual o trimestral"
    if not period and ind.get("annual") and len(years) == 1:
        period = str(next(iter(years)))  # serie anual: el ano escrito es el periodo citado
    if not period and (any(y < published_year - 1 for y in years) or _NOT_CURRENT.search(sn)):
        return "habla del pasado sin periodo comprobable"
    # Territorio: nombrado en la frase (el mas cercano a la cifra si hay varios) o el del medio.
    named = _named_positions(sn)
    if regions:
        if named:
            return "nombra a la vez una comunidad y un pais: no se atribuye"
        if geo not in regions:
            return "el territorio no es la comunidad nombrada"
        if len(regions) > 1:
            dist = sorted(min(abs(p - q) for p in ps for q in positions) for ps in regions.values())
            mine = min(abs(p - q) for p in regions[geo] for q in positions)
            if mine != dist[0] or dist[0] == dist[1]:
                return "varias comunidades: la cifra no es inequivocamente de la propuesta"
        return _finish(sentence, indicator, ind, geo, value, period, direction, sn)
    others = {
        iso
        for iso, names in world_countries().items()
        if iso not in named and any(_word_in(n, sn) for n in names)
    }
    if others:
        return "nombra un territorio sin serie oficial registrada"
    if geo not in indicators()["geo_names"]:
        return "territorio desconocido"
    if len(named) > 1:
        dist = {iso: min(abs(p - q) for p in ps for q in positions) for iso, ps in named.items()}
        best = sorted(dist.items(), key=lambda kv: kv[1])
        if geo != best[0][0] or best[0][1] == best[1][1]:
            return "varios territorios: la cifra no es inequivocamente del propuesto"
    elif named:
        if geo not in named:
            return "el territorio no es el nombrado en la frase"
    else:
        if ind.get("requires_explicit_geo") or geo != default_geo:
            return "territorio no nombrado en la frase"
        if any(_word_in(normalize(m), sn) for m in indicators()["foreign_markers"]):
            return "habla de otro pais sin nombrarlo"
    return _finish(sentence, indicator, ind, geo, value, period, direction, sn)


def _finish(sentence, indicator, ind, geo, value, period, direction, sn) -> ClaimCandidate:
    if not ind.get("directional", True) or direction not in ("sube", "baja"):
        direction = None
    elif not (_UP if direction == "sube" else _DOWN).search(sn):
        direction = None  # el sentido solo cuenta si la frase lo dice con un verbo reconocible
    return ClaimCandidate(sentence[:600], indicator, geo, value, ind["unit"], direction, period)
