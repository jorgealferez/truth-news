"""GDELT DOC 2.0: volumen de cobertura mundial de un tema y hemeroteca de articulos con fecha.

Contexto global y archivo (desde 2017), no veredictos. GDELT pide como maximo una peticion cada 5 s.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from urllib.parse import urlencode

import httpx

from truthnews.data import client

BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
MIN_INTERVAL_S = 5.5
_last_call = 0.0


def _get(params: dict, transport: httpx.BaseTransport | None, sleep, retries: int) -> dict | None:
    global _last_call
    url = f"{BASE}?{urlencode({**params, 'format': 'json'})}"
    resp = None
    for attempt in range(retries + 1):
        wait = _last_call + MIN_INTERVAL_S * (attempt + 1) - time.monotonic()
        if wait > 0:
            sleep(wait)
        _last_call = time.monotonic()
        with client(transport) as c:
            resp = c.get(url)
        if resp.status_code != 429:  # 429: GDELT pide esperar; se reintenta con espera creciente
            break
    if resp.status_code != 200 or not resp.headers.get("content-type", "").startswith("application/json"):
        return None
    try:
        return resp.json()
    except ValueError:  # GDELT devuelve a veces JSON vacio o truncado
        return None


def timeline(
    query: str,
    timespan: str = "30d",
    transport: httpx.BaseTransport | None = None,
    sleep=time.sleep,
    retries: int = 2,
) -> list[dict]:
    """Serie diaria del porcentaje de cobertura mundial que menciona `query`."""
    data = _get({"query": query, "mode": "timelinevol", "timespan": timespan}, transport, sleep, retries)
    series = (data or {}).get("timeline", [])
    return series[0].get("data", []) if series else []


class Unavailable(Exception):
    """GDELT no respondio (429 persistente, error o JSON roto): no es lo mismo que "sin resultados"."""


def articles(
    query: str,
    start: datetime,
    end: datetime,
    max_records: int = 25,
    transport: httpx.BaseTransport | None = None,
    sleep=time.sleep,
    retries: int = 2,
    strict: bool = False,
) -> list[dict]:
    """Articulos de la prensa mundial entre `start` y `end`: fecha, titular, dominio, idioma y URL.

    Con `strict`, un fallo de GDELT lanza `Unavailable` en vez de devolver una lista vacia.
    """
    params = {
        "query": query,
        "mode": "artlist",
        "maxrecords": max_records,
        "sort": "hybridrel",
        "startdatetime": f"{start:%Y%m%d%H%M%S}",
        "enddatetime": f"{end:%Y%m%d%H%M%S}",
    }
    data = _get(params, transport, sleep, retries)
    if data is None and strict:
        raise Unavailable(query)
    out = []
    for a in (data or {}).get("articles", []):
        try:
            seen = datetime.strptime(a["seendate"], "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        except (KeyError, ValueError):
            continue
        out.append(
            {
                "date": seen,
                "title": " ".join((a.get("title") or "").split()),
                "domain": a.get("domain", ""),
                "language": a.get("language", ""),
                "url": a.get("url", ""),
            }
        )
    return out
