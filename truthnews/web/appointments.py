"""Nombramientos y ceses del BOE para la web: un dia por pagina, cacheado en memoria y citado.

Sin tablas: cada dia se lee del sumario del BOE (truthnews.data.nombramientos). Un dia pasado con datos no
cambia y se guarda mientras viva el proceso; hoy o una respuesta vacia se vuelven a pedir a los 10 min.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from truthnews.classify import normalize
from truthnews.data import nombramientos as nb
from truthnews.models import Article

_PARTICLES = frozenset(["de", "del", "la", "las", "los", "el", "y", "e", "para", "con", "en", "a"])
RETRY_SECONDS = 600
MAX_DAYS_CACHED = 120
LOOKBACK_DAYS = 4
MENTION_DAYS = 60
MENTIONS_PER_PERSON = 3


class BoeDays:
    def __init__(self, transport: httpx.BaseTransport | None = None, clock=time.monotonic) -> None:
        self._transport = transport
        self._clock = clock
        self._cache: dict[date, tuple[float, list[nb.Disposicion]]] = {}
        self._lock = threading.Lock()

    def day(self, d: date, today: date) -> list[nb.Disposicion]:
        with self._lock:
            hit = self._cache.get(d)
        if hit and ((hit[1] and d < today) or self._clock() - hit[0] < RETRY_SECONDS):
            return hit[1]
        try:
            items = nb.nombramientos(d, transport=self._transport)
        except httpx.HTTPError:
            items = []
        with self._lock:
            if len(self._cache) >= MAX_DAYS_CACHED:
                self._cache.clear()
            self._cache[d] = (self._clock(), items)
        return items

    def latest(self, today: date) -> tuple[date, list[nb.Disposicion]]:
        """El BOE mas reciente con disposiciones de personal (hoy o hasta LOOKBACK_DAYS atras)."""
        for back in range(LOOKBACK_DAYS):
            d = today - timedelta(days=back)
            items = self.day(d, today)
            if items:
                return d, items
        return today, []


def dept_name(raw: str) -> str:
    """'MINISTERIO DE LA PRESIDENCIA' -> 'Ministerio de la Presidencia' (el BOE los da en mayusculas)."""
    words = raw.lower().split()
    return " ".join(w if (i and w in _PARTICLES) else w.capitalize() for i, w in enumerate(words))


def view(items: list[nb.Disposicion]) -> dict:
    """Primero nombramientos y ceses de una persona, por organo; el resto (colectivos, destinos...) aparte."""
    named: dict[str, list[nb.Disposicion]] = {}
    rest: list[nb.Disposicion] = []
    for i in items:
        if i.tipo in ("nombramiento", "cese") and i.persona:
            named.setdefault(dept_name(i.departamento) or "—", []).append(i)
        else:
            rest.append(i)
    counts = {
        "nombramiento": sum(1 for i in items if i.tipo == "nombramiento"),
        "cese": sum(1 for i in items if i.tipo == "cese"),
        "total": len(items),
    }
    return {"named": sorted(named.items(), key=lambda kv: -len(kv[1])), "rest": rest, "counts": counts}


def _name_keys(persona: str) -> tuple[str, str] | None:
    """Nombre de pila y primer apellido ('María Dolores Rial de la Calle' -> ('María', 'Rial'))."""
    words = [w for w in persona.split() if w.lower() not in _PARTICLES]
    if len(words) < 2:
        return None
    surname = words[-2] if len(words) >= 3 else words[-1]
    return words[0], surname


def _word(needle: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text) is not None


def mentions(session: Session, people: list[str], until) -> dict[str, list[Article]]:
    """Noticias rastreadas de los ultimos 60 dias que nombran a cada persona (nombre y primer apellido)."""
    out: dict[str, list[Article]] = {}
    since = until - timedelta(days=MENTION_DAYS)
    for persona in dict.fromkeys(people):
        keys = _name_keys(persona)
        if not keys:
            continue
        first, surname = keys
        rows = session.scalars(
            select(Article)
            .options(joinedload(Article.outlet))
            .where(
                Article.published_at >= since,
                or_(Article.title.ilike(f"%{surname}%"), Article.summary.ilike(f"%{surname}%")),
            )
            .order_by(Article.published_at.desc())
            .limit(50)
        )
        nf, ns = normalize(first), normalize(surname)
        hits = []
        for a in rows:
            text = normalize(f"{a.title} {a.summary or ''}")
            if _word(ns, text) and _word(nf, text):
                hits.append(a)
            if len(hits) == MENTIONS_PER_PERSON:
                break
        if hits:
            out[persona] = hits
    return out
