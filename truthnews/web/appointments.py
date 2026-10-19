"""Nombramientos y ceses del BOE para la web: un dia por pagina, cacheado en memoria y citado.

Sin tablas: cada dia se lee del sumario del BOE (truthnews.data.nombramientos). Un dia pasado con datos no
cambia y se guarda mientras viva el proceso; hoy o una respuesta vacia se vuelven a pedir a los 10 min.
"""

from __future__ import annotations

import threading
import time
from datetime import date, timedelta

import httpx

from truthnews.data import nombramientos as nb

_PARTICLES = frozenset(["de", "del", "la", "las", "los", "el", "y", "e", "para", "con", "en", "a"])
RETRY_SECONDS = 600
MAX_DAYS_CACHED = 120
LOOKBACK_DAYS = 4


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
