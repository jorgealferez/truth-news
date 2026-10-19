"""Nombramientos y ceses del BOE (seccion II.A del sumario diario): quien, que cargo, que organo y cuando.

Fuente: API de datos abiertos del BOE (`/datosabiertos/api/boe/sumario/AAAAMMDD`), la misma que usa
`truthnews.data.boe`. Solo se lee el sumario (titulo, departamento, epigrafe y enlace); cada registro
enlaza su disposicion para citarla. La persona y el cargo se extraen del titulo con reglas: si no se
reconocen se dejan vacios, nunca se inventan.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from datetime import date

import httpx

from truthnews.data import client

BASE = "https://www.boe.es/datosabiertos/api/boe/sumario"
SECTION = "2A"  # II. Autoridades y personal. - A. Nombramientos, situaciones e incidencias

_NAME_WORD = r"[A-ZÁÉÍÓÚÑÜ][\wÁÉÍÓÚÑÜáéíóúñü'’.-]*"
_LINK = r"(?:de|del|de la|de los|de las|y|i)"
_PERSON = re.compile(rf"\b(?:don|doña|D\.|D\.ª|Dña\.)\s+({_NAME_WORD}(?:\s+(?:{_LINK}\s+)?{_NAME_WORD})*)")
_NOMBRA = re.compile(
    r"\bse (?:nombra|designa)n?\s+(?:para\s+(?:el\s+|la\s+)?)?(.+?),?\s+al?\s+"
    r"(?:(?:el|la)\s+)?(?:[^,]*?\s)?(?:don|doña)\b",
    re.I,
)
_CESE = re.compile(
    r"\bcese\b.*?\b(?:como|en el|en la)\s+(.+?)(?:,\s+(?:a petición|por)\b|,?\s+y\s+se\s+nombra\b|\.$|$)",
    re.I,
)

KINDS = (
    ("cese", ("cese", "ceses")),
    ("nombramiento", ("nombramiento", "nombramientos", "designaciones", "designación")),
    ("destino", ("destinos", "adscripciones", "libre designación")),
    ("ascenso", ("ascensos", "integraciones")),
    ("situacion", ("situaciones", "reingresos", "jubilaciones", "excedencias", "renuncias", "bajas")),
)


@dataclass
class Disposicion:
    id: str
    fecha: str
    tipo: str
    departamento: str
    epigrafe: str
    titulo: str
    url: str
    persona: str = ""
    cargo: str = ""


def _as_list(node) -> list:
    if isinstance(node, list):
        return node
    return [node] if node else []


def kind_of(epigrafe: str, titulo: str) -> str:
    """Tipo de disposicion por su epigrafe; si el epigrafe no lo dice, por el titulo."""
    ep = epigrafe.lower()
    for kind, words in KINDS:
        if any(w in ep for w in words):
            return kind
    t = titulo.lower()
    if re.search(r"\bcese\b", t):
        return "cese"
    if re.search(r"\bse (?:nombra|designa)", t):
        return "nombramiento"
    return "otro"


def person_of(titulo: str) -> str:
    m = _PERSON.search(titulo)
    return m.group(1).rstrip(".,") if m else ""


def post_of(titulo: str, tipo: str) -> str:
    rx = _CESE if tipo == "cese" else _NOMBRA
    m = rx.search(titulo)
    return m.group(1).strip().rstrip(".,") if m else ""


def parse(payload: dict, day: date) -> list[Disposicion]:
    """Disposiciones de la seccion II.A de un sumario del BOE ya descargado."""
    out: list[Disposicion] = []
    sumario = (payload.get("data") or {}).get("sumario") or {}
    for diario in _as_list(sumario.get("diario")):
        for sec in _as_list(diario.get("seccion")):
            if sec.get("codigo") != SECTION:
                continue
            for dep in _as_list(sec.get("departamento")):
                groups = [(ep.get("nombre", ""), ep.get("item")) for ep in _as_list(dep.get("epigrafe"))]
                groups.append(("", dep.get("item")))
                for epigrafe, items in groups:
                    for it in _as_list(items):
                        titulo = (it.get("titulo") or "").strip()
                        if not titulo or not it.get("identificador"):
                            continue
                        url = it.get("url_html")
                        url = url if isinstance(url, str) else (it.get("url_pdf") or {}).get("texto", "")
                        tipo = kind_of(epigrafe, titulo)
                        out.append(
                            Disposicion(
                                id=it["identificador"],
                                fecha=day.isoformat(),
                                tipo=tipo,
                                departamento=(dep.get("nombre") or "").strip(),
                                epigrafe=epigrafe,
                                titulo=titulo,
                                url=url,
                                persona=person_of(titulo),
                                cargo=post_of(titulo, tipo) if tipo in ("nombramiento", "cese") else "",
                            )
                        )
    return out


def nombramientos(day: date, transport: httpx.BaseTransport | None = None) -> list[Disposicion]:
    """Nombramientos, ceses y demas incidencias de personal publicadas en el BOE de un dia."""
    with client(transport) as c:
        resp = c.get(f"{BASE}/{day:%Y%m%d}", headers={"Accept": "application/json"})
    if resp.status_code != 200:
        return []
    return parse(resp.json(), day)


def as_dicts(items: list[Disposicion]) -> list[dict]:
    return [asdict(i) for i in items]
