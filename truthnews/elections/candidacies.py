"""Candidaturas presentadas y proclamadas, tal como las publica el BOE (ADR 0036, 18e).

Las Juntas Electorales Provinciales publican en un solo documento del BOE todas las candidaturas de cada
circunscripcion: "JUNTA ELECTORAL DE <PROVINCIA>", la camara, y por candidatura "N. NOMBRE (SIGLAS)"
seguido de sus candidatos. De ahi sale la lista completa de formaciones que concurren (no solo las que
tienen escano), donde se presentan y quien encabeza cada lista. Sin tablas: el documento se lee una vez.
"""

from __future__ import annotations

import html
import re
from dataclasses import dataclass, field

from truthnews.classify import normalize

_P = re.compile(r"<p[^>]*>(.*?)</p>", re.S)
_TAGS = re.compile(r"<[^>]+>")
_BOARD = re.compile(r"^JUNTA ELECTORAL (?:PROVINCIAL )?DE (.+)$")
_SEAT = re.compile(r"^Circunscripci[oó]n electoral:\s*(.+)$")
_LIST = re.compile(r"^(\d+)\.\s+(.+?)\s*\(([^()]+)\)\s*\.?$")
_PERSON = re.compile(r"^(\d+)\.\s+(.+?)\.?$")
TITLE = re.compile(r"\bcandidaturas (proclamadas|presentadas)\b")


@dataclass
class Formation:
    name: str
    acronym: str
    congreso: list[str] = field(default_factory=list)
    senado: list[str] = field(default_factory=list)
    heads: dict[str, str] = field(default_factory=dict)  # circunscripcion del Congreso -> cabeza de lista

    @property
    def key(self) -> str:
        return normalize(self.acronym).replace(" ", "")

    @property
    def reach(self) -> int:
        return len(set(self.congreso) | set(self.senado))


def _paras(markup: str) -> list[str]:
    return [re.sub(r"\s+", " ", html.unescape(_TAGS.sub("", p))).strip() for p in _P.findall(markup)]


def _place(raw: str) -> str:
    words = raw.strip().lower().split()
    small = {"de", "del", "la", "las", "los", "el", "y"}
    return " ".join(w if i and w in small else w.capitalize() for i, w in enumerate(words))


def parse(markup: str) -> list[Formation]:
    """Formaciones del documento, de la que se presenta en mas circunscripciones a la que menos."""
    by_key: dict[str, Formation] = {}
    province = seat = chamber = None
    current: Formation | None = None
    want_head = False
    for p in _paras(markup):
        if m := _BOARD.match(p):
            province, seat, chamber, current = _place(m.group(1)), None, None, None
            continue
        if p in ("CONGRESO DE LOS DIPUTADOS", "SENADO"):
            chamber, seat, current = ("congreso" if p.startswith("CONGRESO") else "senado"), None, None
            continue
        if m := _SEAT.match(p):
            seat = m.group(1).strip()
            continue
        if not province or not chamber:
            continue
        m = _LIST.match(p)
        if m and not re.search(r"[a-záéíóúñü]", m.group(2)):
            name, acronym = m.group(2).strip(), m.group(3).strip()
            f = Formation(name, acronym)
            current = by_key.setdefault(f.key, f)
            where = seat or province
            places = current.congreso if chamber == "congreso" else current.senado
            if where not in places:
                places.append(where)
            want_head = chamber == "congreso"
            continue
        if want_head and current and (m := _PERSON.match(p)) and m.group(1) == "1":
            current.heads.setdefault(province, m.group(2).strip())
            want_head = False
    return sorted(by_key.values(), key=lambda f: (-f.reach, f.name))


def kind_of(title: str) -> str | None:
    """'proclamadas' o 'presentadas' si el titulo del BOE es una publicacion de candidaturas."""
    m = TITLE.search(normalize(title))
    return m.group(1) if m else None
