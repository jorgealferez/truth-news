"""Consejo de Ministros frente al BOE: lo que el Gobierno anuncia que aprobo y si ya consta publicado.

Fuente del anuncio: las referencias del Consejo en lamoncloa.gob.es (robots.txt lo permite). Solo se leen
los reales decretos del SUMARIO: los acuerdos de autorizacion, informes y anteproyectos no se publican en el
BOE como tales y compararlos daria falsos "no publicado". Fuente de la publicacion: el sumario del BOE
(`truthnews.data.boe`). Un real decreto consta cuando el BOE publica uno del mismo tipo, fechado ese dia
("de 13 de octubre") y con el mismo objeto ("por el que ..."). Sin calificativos: publicado (con las dos
citas), todavia no publicado o, pasados PUBLISH_DAYS dias, aun no publicado.
"""

from __future__ import annotations

import html as htmllib
import re
from dataclasses import dataclass
from datetime import date, timedelta

import httpx

from truthnews.classify import normalize
from truthnews.data import client

SITE = "https://www.lamoncloa.gob.es"
INDEX = f"{SITE}/consejodeministros/referencias/Paginas/index.aspx"
PUBLISH_DAYS = 30
MATCH_MIN = 0.8  # parte del objeto mas corto que aparece en el otro (el BOE anade organo y "doña")
MONTHS = [
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
]
# Del mas largo al mas corto: "REAL DECRETO-LEY" empieza tambien por "REAL DECRETO".
KINDS = (
    ("real-decreto-ley", "REAL DECRETO-LEY", "Real Decreto-ley"),
    ("real-decreto-legislativo", "REAL DECRETO LEGISLATIVO", "Real Decreto Legislativo"),
    ("real-decreto", "REAL DECRETO", "Real Decreto"),
)
_LINK = re.compile(r'href="(/consejodeministros/referencias/Paginas/\d{4}/(\d{8})-referencia[^"]*\.aspx)"')
_SUMARIO = re.compile(r"<h2>\s*SUMARIO\s*</h2>(.*?)(?:<h2>\s*AMPLIACI|</section>)", re.S | re.I)
_BLOCK = re.compile(r"<h3[^>]*>(.*?)</h3>|<li[^>]*>(.*?)</li>", re.S | re.I)
_TAG = re.compile(r"<[^>]+>")
# Cabecera que no es objeto: "REAL DECRETO" (La Moncloa) o "Real Decreto 806/2026, de 5 de octubre," (BOE).
_HEADER = re.compile(r"^real decreto(?:-ley| legislativo)?(?: \d+/\d{4}, de \d+ de [a-z]+,)?\s*")
_WORD = re.compile(r"[a-z0-9]+")
_STOP = frozenset(
    [
        "a",
        "al",
        "de",
        "del",
        "el",
        "la",
        "las",
        "los",
        "lo",
        "en",
        "y",
        "e",
        "o",
        "u",
        "se",
        "que",
        "por",
        "para",
        "con",
        "su",
        "sus",
        "un",
        "una",
    ]
)


@dataclass
class Decreto:
    fecha: str  # dia del Consejo (AAAA-MM-DD)
    ministerio: str
    tipo: str  # real-decreto | real-decreto-ley | real-decreto-legislativo
    texto: str
    url: str  # referencia del Consejo en La Moncloa


def _text(fragment: str) -> str:
    return " ".join(htmllib.unescape(_TAG.sub(" ", fragment)).split())


def reference_links(page: str) -> list[tuple[date, str]]:
    """Referencias enlazadas desde el indice, la mas reciente primero y sin repetir."""
    seen: dict[str, date] = {}
    for path, stamp in _LINK.findall(page):
        try:
            seen.setdefault(SITE + path, date(int(stamp[:4]), int(stamp[4:6]), int(stamp[6:])))
        except ValueError:
            continue
    return sorted(((d, u) for u, d in seen.items()), key=lambda p: (p[0], p[1]), reverse=True)


def kind_of(text: str) -> str | None:
    for slug, prefix, _ in KINDS:
        if text.startswith(prefix):
            return slug
    return None


def parse_reference(page: str, day: date, url: str) -> list[Decreto]:
    """Reales decretos del SUMARIO de una referencia, con el ministerio que los propone."""
    m = _SUMARIO.search(page)
    if not m:
        return []
    out, ministerio = [], ""
    for head, item in _BLOCK.findall(m.group(1)):
        if head:
            ministerio = _text(head)
            continue
        texto = _text(item)
        tipo = kind_of(texto)
        if tipo:
            out.append(Decreto(day.isoformat(), ministerio, tipo, texto, url))
    return out


def _words(text: str) -> set[str]:
    obj = _HEADER.sub("", normalize(text).strip())
    return {w for w in _WORD.findall(obj) if w not in _STOP}


def similarity(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    return len(wa & wb) / min(len(wa), len(wb)) if wa and wb else 0.0


def dated(day: date) -> str:
    """Como fecha el BOE una norma: 'de 13 de octubre'."""
    return f"de {day.day} de {MONTHS[day.month - 1]}"


def match(dec: Decreto, boe_items: list[dict]) -> dict | None:
    """El titulo del BOE que publica este real decreto: mismo tipo, misma fecha y el objeto mas parecido."""
    day = date.fromisoformat(dec.fecha)
    title_prefix = next(t for slug, _, t in KINDS if slug == dec.tipo)
    stamp = dated(day)
    best, best_score = None, MATCH_MIN
    for it in boe_items:
        title = it.get("titulo") or ""
        head = title.split(",", 1)[0]
        # "Real Decreto 841/2026" no debe casar con "Real Decreto-ley 30/2026" ni al reves.
        if not re.fullmatch(rf"{re.escape(title_prefix)} \d+/\d{{4}}", head) or stamp not in title:
            continue
        score = similarity(dec.texto, title)
        if score >= best_score:
            best, best_score = it, score
    return best


def status(dec: Decreto, published: dict | None, today: date) -> str:
    if published:
        return "publicado"
    days = (today - date.fromisoformat(dec.fecha)).days
    return "no_publicado" if days >= PUBLISH_DAYS else "pendiente"


def boe_window(dec: Decreto, today: date) -> list[date]:
    """Dias del BOE en que pudo publicarse: del dia del Consejo a hoy, sin domingos (no hay BOE)."""
    start = date.fromisoformat(dec.fecha)
    return [d for k in range((today - start).days + 1) if (d := start + timedelta(days=k)).weekday() != 6]


def fetch(url: str, transport: httpx.BaseTransport | None = None) -> str:
    """Una pagina de La Moncloa; vacio si no responde 200 (no se insiste ni se evade un bloqueo)."""
    with client(transport) as c:
        resp = c.get(url)
    return resp.text if resp.status_code == 200 else ""


def latest(limit: int = 6, transport: httpx.BaseTransport | None = None) -> list[Decreto]:
    """Reales decretos de las ultimas `limit` referencias del Consejo de Ministros."""
    out: list[Decreto] = []
    for day, url in reference_links(fetch(INDEX, transport))[:limit]:
        out.extend(parse_reference(fetch(url, transport), day, url))
    return out
