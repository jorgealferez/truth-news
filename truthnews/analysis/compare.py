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
# "personas" no dice que les paso: el contexto decide si son muertos, heridos, detenidos o evacuados. Sin
# contexto no se compara ("mata a dos personas" frente a "11 personas resultaron heridas" no es disputa).
_PERSONAS_CONTEXT = (
    ("muertos", re.compile(r"\b(mata|matan|mato|mataron|muert|fallec|mueren|murieron|pierden la vida)")),
    ("heridos", re.compile(r"\bherid")),
    ("detenidos", re.compile(r"\b(detenid|detencion|arrestad)")),
    ("evacuados", re.compile(r"\b(evacuad|desalojad|realojad)")),
)
# Dos cifras del mismo sustantivo solo se comparan si hablan del mismo hecho (ADR 0016). Un balance que se
# actualiza o una discrepancia real se mueven dentro de un orden de magnitud; "12 migrantes" ocultados en una
# casa frente a "500" desalojados, o "50 detenidos" en Milan frente a "2.000" en Francia, son hechos
# distintos. Excepcion: dos cifras atribuidas ("segun ...") son versiones del mismo recuento.
SAME_FACT_RATIO = 3.0
SAME_FACT_MIN_GAP = 10
_ATTRIBUTED = re.compile(r"\bsegun\b")
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
    "Sigue",
    "Alert",
    "Alerta",
    "Última",
    "Ultima",
    "Hora",
    "Así",
    "Aunque",
    "Cuando",
    "Donde",
}
MAX_CONSENSUS = 12  # nombres que mas medios comparten; una lista de 60 nombres no informa
MAX_OMISSIONS = 5


# A quien atribuye cada medio la responsabilidad (el encuadre que mas cambia entre medios). Se busca en el
# titular, el resumen y el arranque del texto; el objetivo debe ser un nombre propio o una institucion.
_CAP = r"[A-ZÁÉÍÓÚÑ][\wáéíóúñ]+"
_TARGET = r"((?:el |la |los |las |al )?" + _CAP + r"(?:\s(?:de |del |de la |y )?" + _CAP + r"){0,3})"
_BLAME = re.compile(
    r"\b(?:culpa|culpan|culpó|culparon|responsabiliza|responsabilizan|responsabilizó|acusa|acusan|acusó|"
    r"señala|señalan|señaló|apunta|apuntan|apuntó)\s+(?:a|al|de|del)\s+"
    + _TARGET
    + r"|\b(?:por culpa|a causa|responsabilidad) (?:de|del)\s+"
    + _TARGET
    + r"|\b(?:carga|cargan|cargó|arremete|arremeten|arremetió)\s+contra\s+"
    + _TARGET
)
_ARTICLE = re.compile(r"^(?:el|la|los|las|al)\s+")
_INSTITUTIONS = {"Gobierno", "Policía", "Policia"}  # no son nombres propios utiles, pero si culpables


def blames(text: str) -> list[str]:
    """Objetivos a los que el texto atribuye culpa o responsabilidad, en orden de aparicion."""
    out: list[str] = []
    for m in _BLAME.finditer(text or ""):
        target = next(g for g in m.groups() if g)
        words = _ARTICLE.sub("", target).split()
        skip = _SKIP_PROPER - _INSTITUTIONS
        while words and words[-1] in skip | {"y", "de", "del"}:
            words.pop()
        name = " ".join(words)
        if name and name.split()[0] not in skip and name not in out:
            out.append(name)
    return out


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
    agreed_figures: list[tuple[str, int, int]] = field(default_factory=list)  # (sustantivo, valor, medios)
    shared_names: list[tuple[str, int]] = field(default_factory=list)  # (nombre, medios), mas citados antes
    omissions: dict[str, list[str]] = field(default_factory=dict)
    loaded: dict[str, list[str]] = field(default_factory=dict)
    blame: dict[str, list[str]] = field(default_factory=dict)  # medio -> a quien culpa
    basis: str = "titulares y resumenes"

    @property
    def blame_differs(self) -> bool:
        """Varios medios culpan y no todos a los mismos."""
        targets = [frozenset(t) for t in self.blame.values()]
        return len(targets) >= 2 and len(set(targets)) >= 2

    def dispute_summaries(self) -> list[DisputeSummary]:
        return [summarize_dispute(figs[0].noun, figs) for figs in self.disputes.values()]


QUALIFIER_LABEL = {
    "mas de": "más de",
    "menos de": "menos de",
    "casi": "casi",
    "unos": "unos",
    "unas": "unas",
    "al menos": "al menos",
    "cerca de": "cerca de",
}


@dataclass
class DisputeSummary:
    noun: str
    low: float
    high: float
    n_outlets: int
    mode: float  # la cifra que mas medios dan
    mode_n: int
    groups: list[tuple[float, list[Figure]]]  # cifra -> medios que la dan, de mas a menos medios


def summarize_dispute(noun: str, figs: list[Figure]) -> DisputeSummary:
    """Agrupa una disputa por cifra: rango, cifra mas repetida y que medios dan cada una."""
    by_value: dict[float, list[Figure]] = defaultdict(list)
    for f in figs:
        by_value[f.value].append(f)
    groups = sorted(by_value.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    values = [f.value for f in figs]
    return DisputeSummary(noun, min(values), max(values), len(figs), groups[0][0], len(groups[0][1]), groups)


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
        noun = _COUNTABLE[m.group(4)]
        if noun == "personas":
            around = f"{tn[max(0, m.start() - 20) : m.start()]} | {tn[m.end() : m.end() + 25]}"
            noun = next((n for n, rx in _PERSONAS_CONTEXT if rx.search(around)), None)
            if noun is None:
                continue
        out.append((noun, value, (m.group(1) or "").strip(), frag))
    return out


def same_fact(a: Figure, b: Figure) -> bool:
    """Si dos cifras del mismo sustantivo pueden hablar del mismo hecho (ADR 0016)."""
    low, high = sorted((a.value, b.value))
    if high <= SAME_FACT_RATIO * low or high - low <= SAME_FACT_MIN_GAP:
        return True
    return bool(_ATTRIBUTED.search(a.text) and _ATTRIBUTED.search(b.text))


def same_facts(figs: list[Figure]) -> list[list[Figure]]:
    """Reparte las cifras de un sustantivo en hechos, el que mas medios cuentan primero.

    Ancla: la cifra que mas medios dan (a igualdad, la mayor). Entran en su hecho las cifras compatibles
    con ella; con el resto se repite.
    """
    out: list[list[Figure]] = []
    rest = list(figs)
    while rest:
        counts = Counter(f.value for f in rest)
        anchor = next(f for f in rest if f.value == max(counts, key=lambda v: (counts[v], v)))
        fact = [f for f in rest if same_fact(anchor, f)]
        out.append(fact)
        rest = [f for f in rest if not any(f is g for g in fact)]
    return out


def proper_nouns(text: str) -> set[str]:
    text = re.sub(r"\s+", " ", text or "").strip()  # el inicio de frase se detecta con un solo espacio
    out = set()
    for m in _PROPER.finditer(text):
        words = m.group(1).split()
        while words and words[0] in _SKIP_PROPER:
            words.pop(0)
        while words and words[-1] in _SKIP_PROPER:  # "Comunidad Valenciana Pero" -> "Comunidad Valenciana"
            words.pop()
        if words:
            out.add(" ".join(words))
    return out


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

    # Cifras: por sustantivo, el valor que da cada medio. De cada articulo cuenta la primera cifra (la del
    # titular, si la hay: el resto suele ser un desglose, "Paris registro 855"); de cada medio, su ultimo
    # articulo con esa cifra (un balance se actualiza).
    per_noun: dict[str, dict[str, Figure]] = defaultdict(dict)
    for outlet, arts in by_outlet.items():
        for a in sorted(arts, key=lambda x: x.published_at):
            if _LIVE.search(normalize(a.title)):
                continue  # un directo mezcla datos de muchos momentos: no se compara
            lead = f"{a.title}. {a.summary or ''} {(a.content_text or '')[:LEAD_CHARS]}"
            seen: set[str] = set()
            for noun, value, qual, frag in figures(lead):
                if noun in seen:
                    continue
                seen.add(noun)
                prev = per_noun[noun].get(outlet)
                if prev is None or a.published_at >= prev.published_at:
                    per_noun[noun][outlet] = Figure(noun, value, qual, outlet, a.published_at, frag)
    for noun, by in per_noun.items():
        for i, fact in enumerate(same_facts(list(by.values()))):
            if len(fact) < 2:
                continue
            values = [f.value for f in fact]
            if max(values) > 1.1 * min(values):
                key = noun if i == 0 else f"{noun} ·{i + 1}"
                comp.disputes[key] = sorted(fact, key=lambda f: f.published_at)
            else:
                comp.consensus.append(f"{noun}: {int(min(values)):,}".replace(",", "."))
                comp.agreed_figures.append((noun, int(min(values)), len(fact)))

    # Omisiones: nombres propios que cuenta la mayoria (>= 3 medios) y un medio no. Solo se juzga a los
    # medios de los que tenemos el texto completo: con un titular, no mencionar algo no es omitirlo.
    if len(by_outlet) >= 3:
        nouns = {o: proper_nouns(text_of(arts)) for o, arts in by_outlet.items()}
        counts = Counter(n for s in nouns.values() for n in s)
        majority = {n for n, c in counts.items() if c >= max(3, (len(by_outlet) + 1) // 2)}
        ranked = sorted(majority, key=lambda n: (-counts[n], n))
        comp.consensus += ranked[:MAX_CONSENSUS]
        comp.shared_names = [(n, counts[n]) for n in ranked]
        for o, s in nouns.items():
            if not any(a.content_text for a in by_outlet[o]):
                continue
            # Lo que mas medios cuentan y este no: las omisiones mas significativas primero.
            missing = [n for n in ranked if n not in s][:MAX_OMISSIONS]
            if missing:
                comp.omissions[o] = sorted(missing)

    for outlet, arts in by_outlet.items():
        found: list[str] = []
        for a in arts:
            for name in blames(f"{a.title}. {a.summary or ''} {(a.content_text or '')[:LEAD_CHARS]}"):
                if name not in found:
                    found.append(name)
        if found:
            comp.blame[outlet] = found
        words = loaded_words(text_of(arts), arts[0].language)
        if words:
            comp.loaded[outlet] = words
    return comp
