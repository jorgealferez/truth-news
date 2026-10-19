"""Ejecucion del Presupuesto del Estado para la web: el ultimo extracto de la IGAE, cacheado en memoria.

Sin tablas: la IGAE publica un extracto al mes; se pide como mucho cada 12 h (cada 10 min si fallo).
"""

from __future__ import annotations

import threading
import time

from truthnews.data import igae
from truthnews.web.appointments import dept_name

REFRESH_SECONDS = 12 * 3600
RETRY_SECONDS = 600


class LatestExtract:
    def __init__(self, fetch=igae.latest, clock=time.monotonic) -> None:
        self._fetch = fetch
        self._clock = clock
        self._value: igae.Extracto | None = None
        self._at = -1e18
        self._lock = threading.Lock()

    def get(self) -> igae.Extracto | None:
        with self._lock:
            ttl = REFRESH_SECONDS if self._value else RETRY_SECONDS
            if self._clock() - self._at < ttl:
                return self._value
        try:
            value = self._fetch()
        except Exception:
            value = None
        with self._lock:
            self._at = self._clock()
            # Si la IGAE falla, se sigue mostrando el ultimo extracto bueno (con su fecha).
            self._value = value or self._value
            return self._value


def view(ex: igae.Extracto) -> dict:
    """Ministerios ordenados por presupuesto, con su inversion al lado; capitulos de ingresos."""
    inv = {p.nombre: p for p in ex.inversiones}
    rows = [
        {"nombre": dept_name(p.nombre), "gasto": p, "inversion": inv.get(p.nombre)}
        for p in sorted(ex.gastos, key=lambda p: -p.creditos)
        if p.creditos > 0
    ]
    chapters = [p for p in ex.ingresos if p.nombre[:2].rstrip(".").isdigit()]
    return {"rows": rows, "ingresos": chapters}
