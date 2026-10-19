"""Consejo de Ministros frente al BOE en la web: lo anunciado y si consta publicado, con las dos citas.

Sin tablas: las referencias del Consejo y los sumarios del BOE se leen en segundo plano cada REFRESH_SECONDS
y el resultado vive en memoria; la pagina muestra el ultimo calculado y nunca espera a la red. Un dia del BOE
que no se pudo leer deja "sin comprobar" (nunca "aun no publicado") lo que podia estar en el.
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from datetime import date

import httpx

from truthnews.data import boe, consejo
from truthnews.web.appointments import RETRY_SECONDS, BoeDays

REFRESH_SECONDS = 3 * 3600
REFERENCES = 6  # ultimas referencias del Consejo (unas seis semanas)


@dataclass
class Row:
    decreto: consejo.Decreto
    estado: str  # publicado | pendiente | no_publicado | sin_comprobar
    boe: dict | None = None
    boe_fecha: str = ""
    dias: int = 0


@dataclass
class Council:
    fecha: str
    url: str
    rows: list[Row] = field(default_factory=list)

    def count(self, estado: str) -> int:
        return sum(r.estado == estado for r in self.rows)


def compare(decretos: list[consejo.Decreto], days: BoeDays, today: date) -> list[Council]:
    """Cada real decreto con su publicacion en el BOE (o su ausencia), agrupados por Consejo."""
    out: dict[str, Council] = {}
    for dec in decretos:
        found, complete = None, True
        for d in consejo.boe_window(dec, today):
            items = days.day(d, today)
            complete = complete and (bool(items) or d == today)  # el BOE de hoy puede no haber salido
            hit = consejo.match(dec, items)
            if hit:
                found = (d, hit)
                break
        estado = consejo.status(dec, found[1] if found else None, today)
        if estado == "no_publicado" and not complete:
            estado = "sin_comprobar"
        row = Row(dec, estado, found[1] if found else None, found[0].isoformat() if found else "")
        row.dias = ((found[0] if found else today) - date.fromisoformat(dec.fecha)).days
        out.setdefault(dec.fecha, Council(dec.fecha, dec.url)).rows.append(row)
    return sorted(out.values(), key=lambda c: c.fecha, reverse=True)


class CouncilIndex:
    """Ultimo calculo en memoria, rehecho en segundo plano cada REFRESH_SECONDS."""

    def __init__(
        self,
        days: BoeDays | None = None,
        transport: httpx.BaseTransport | None = None,
        clock=time.monotonic,
        background: bool = True,
        references: int = REFERENCES,
    ) -> None:
        self.days = days or BoeDays(transport=transport, fetch=boe.sumario)
        self._transport = transport
        self._clock = clock
        self._background = background
        self._references = references
        self._result: list[Council] | None = None
        self._computed_at = -1e18
        self._running = False
        self._lock = threading.Lock()

    def councils(self, today: date) -> list[Council] | None:
        """Lo ultimo calculado (None mientras se prepara la primera vez); lanza el recalculo si toca."""
        with self._lock:
            stale = self._clock() - self._computed_at >= REFRESH_SECONDS
            start = stale and not self._running
            if start:
                self._running = True
        if start:
            if self._background:
                threading.Thread(target=self._refresh, args=(today,), name="consejo", daemon=True).start()
            else:
                self._refresh(today)
        with self._lock:
            return self._result

    def _refresh(self, today: date) -> None:
        try:
            decretos = consejo.latest(self._references, transport=self._transport)
            result = compare(decretos, self.days, today) if decretos else None
        except httpx.HTTPError:
            result = None  # La Moncloa no responde: se conserva lo anterior
        with self._lock:
            if result is not None:
                self._result = result
                self._computed_at = self._clock()
            else:  # sin datos nuevos: se reintenta a los RETRY_SECONDS, no a las 3 h
                self._computed_at = self._clock() - REFRESH_SECONDS + RETRY_SECONDS
            self._running = False
