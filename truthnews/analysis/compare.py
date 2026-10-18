"""Comparacion de una historia entre medios: coincidencias y diferencias (ADR 0004).

Todo se calcula en lectura a partir de los articulos de la historia: cifras en disputa, datos que la
mayoria cuenta y algun medio omite, y lenguaje valorativo por medio.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field

from truthnews.classify import normalize

_WORDNUM = {
    "un": 1,
    "una": 1,
    "uno": 1,
    "dos": 2,
    "tres": 3,
    "cuatro": 4,
    "cinco": 5,
    "seis": 6,
    "siete": 7,
    "ocho": 8,
    "nueve": 9,
    "diez": 10,
    "doce": 12,
    "quince": 15,
    "veinte": 20,
    "cien": 100,
}
_COUNTABLE = {
    "detenidos": "detenidos",
    "detenidas": "detenidos",
    "arrestos": "detenidos",
    "arrestados": "detenidos",
    "heridos": "heridos",
    "heridas": "heridos",
    "muertos": "muertos",
    "muertes": "muertos",
    "fallecidos": "muertos",
    "victimas": "victimas",
    "desaparecidos": "desaparecidos",
    "migrantes": "migrantes",
    "inmigrantes": "migrantes",
    "agentes": "agentes",
    "policias": "policias",
    "manifestantes": "manifestantes",
    "desalojados": "desalojados",
    "evacuados": "evacuados",
    "comercios": "comercios",
    "viviendas": "viviendas",
    "votos": "votos",
    "escanos": "escanos",
    "euros": "euros",
    "soldados": "soldados",
    "militares": "soldados",
    "personas": "personas",
}
_NUM = r"(\d{1,3}(?:\.\d{3})+|\d+(?:,\d+)?|" + "|".join(_WORDNUM) + r")"
_FIGURE = re.compile(
    r"(?<!\w)(mas de |menos de |casi |unos |unas |al menos |cerca de )?(?<![\w.,])"
    + _NUM
    + r"(\s+millones\s+de|\s+mil)?(?!\w)\s+(?:\w+\s+)?("
    + "|".join(_COUNTABLE)
    + r")\b"
)
_LIVE = re.compile(r"\b(en directo|directo|ultima hora|minuto a minuto|live)\b")
LEAD_CHARS = 400  # las cifras se toman del titular, el resumen y el arranque del texto
LOADED = {
    "es": [
        "caos",
        "arde",
        "arden",
        "ardiendo",
        "brutal",
        "salvaje",
        "infierno",
        "escandalo",
        "bochornoso",
        "verguenza",
        "golpe",
        "masacre",
        "terror",
        "radical",
        "radicales",
        "ultra",
        "ultras",
        "invasion",
        "avalancha",
        "oleada",
        "asalto",
        "humillacion",
        "demoledor",
        "devastador",
        "sangriento",
        "catastrofe",
        "desastre",
        "okupas",
        "ilegales",
        "dictador",
        "traicion",
        "saqueo",
        "saqueos",
    ],
}
_PROPER = re.compile(r"(?<![.!?]\s)(?<!^)\b([A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{3,})*)")
_SKIP_PROPER = {
    "Gobierno",
    "Policía",
    "Policia",
    "Este",
    "Esta",
    "Estos",
    "Según",
    "Segun",
    "Además",
    "Ademas",
    "Pero",
    "Para",
    "Desde",
    "Durante",
    "Entre",
    "Tras",
    "Todo",
    "Todos",
    "Lunes",
    "Martes",
    "Miércoles",
    "Jueves",
    "Viernes",
    "Sábado",
    "Domingo",
    "Vídeo",
    "Video",
    "Directo",
}


@dataclass
class Figure:
    noun: str
    value: float
    qualifier: str
    outlet: str
    published_at: object
    text: str


@dataclass
class Comparison:
    outlets: list[str]
    disputes: dict[str, list[Figure]] = field(default_factory=dict)
    consensus: list[str] = field(default_factory=list)
    omissions: dict[str, list[str]] = field(default_factory=dict)
    loaded: dict[str, list[str]] = field(default_factory=dict)
    basis: str = "titulares y resumenes"


def _value(raw: str, scale: str) -> float:
    v = float(_WORDNUM[raw]) if raw in _WORDNUM else float(raw.replace(".", "").replace(",", "."))
    if "millones" in scale:
        v *= 1_000_000
    elif "mil" in scale:
        v *= 1_000
    return v


def figures(text: str) -> list[tuple[str, float, str, str]]:
    """(sustantivo canonico, valor, calificador, fragmento) de cada cifra contable del texto."""
    out = []
    tn = normalize(text)
    for m in _FIGURE.finditer(tn):
        value = _value(m.group(2), m.group(3) or "")
        if value < 2 and m.group(2) in ("un", "una", "uno"):
            continue
        frag = tn[max(0, m.start() - 30) : m.end() + 10].strip()
        out.append((_COUNTABLE[m.group(4)], value, (m.group(1) or "").strip(), frag))
    return out


def proper_nouns(text: str) -> set[str]:
    text = re.sub(r"\s+", " ", text or "").strip()  # el inicio de frase se detecta con un solo espacio
    return {m.group(1) for m in _PROPER.finditer(text) if m.group(1).split()[0] not in _SKIP_PROPER}


def loaded_words(text: str, language: str = "es") -> list[str]:
    tn = normalize(text)
    return sorted({w for w in LOADED.get(language, LOADED["es"]) if re.search(rf"(?<!\w){w}(?!\w)", tn)})


def compare(articles: list) -> Comparison:
    """`articles`: objetos con .outlet.name, .title, .summary, .content_text, .published_at, .language."""
    by_outlet: dict[str, list] = defaultdict(list)
    for a in articles:
        by_outlet[a.outlet.name].append(a)
    comp = Comparison(outlets=sorted(by_outlet))
    full = sum(1 for a in articles if a.content_text)
    if full >= max(1, len(articles) // 2):
        comp.basis = "texto completo"

    def text_of(arts) -> str:
        return " ".join(f"{a.title}. {a.summary or ''} {a.content_text or ''}" for a in arts)

    # Cifras: por sustantivo, el valor que da cada medio (el ultimo publicado por ese medio).
    per_noun: dict[str, dict[str, Figure]] = defaultdict(dict)
    for outlet, arts in by_outlet.items():
        for a in sorted(arts, key=lambda x: x.published_at):
            if _LIVE.search(normalize(a.title)):
                continue  # un directo mezcla datos de muchos momentos: no se compara
            lead = f"{a.title}. {a.summary or ''} {(a.content_text or '')[:LEAD_CHARS]}"
            for noun, value, qual, frag in figures(lead):
                prev = per_noun[noun].get(outlet)
                if prev is None or a.published_at >= prev.published_at:
                    per_noun[noun][outlet] = Figure(noun, value, qual, outlet, a.published_at, frag)
    for noun, by in per_noun.items():
        if len(by) < 2:
            continue
        values = [f.value for f in by.values()]
        if max(values) > 1.1 * min(values):
            comp.disputes[noun] = sorted(by.values(), key=lambda f: f.published_at)
        else:
            comp.consensus.append(f"{noun}: {int(min(values)):,}".replace(",", "."))

    # Omisiones: nombres propios que cuenta la mayoria (>= 3 medios) y un medio no. Solo se juzga a los
    # medios de los que tenemos el texto completo: con un titular, no mencionar algo no es omitirlo.
    if len(by_outlet) >= 3:
        nouns = {o: proper_nouns(text_of(arts)) for o, arts in by_outlet.items()}
        counts = Counter(n for s in nouns.values() for n in s)
        majority = {n for n, c in counts.items() if c >= max(3, (len(by_outlet) + 1) // 2)}
        comp.consensus += sorted(majority)
        for o, s in nouns.items():
            if not any(a.content_text for a in by_outlet[o]):
                continue
            missing = sorted(majority - s)
            if missing:
                comp.omissions[o] = missing

    for outlet, arts in by_outlet.items():
        words = loaded_words(text_of(arts), arts[0].language)
        if words:
            comp.loaded[outlet] = words
    return comp
