"""GDELT DOC 2.0: volumen de cobertura mundial de un tema (contexto global, no veredictos)."""

from __future__ import annotations

import time
from urllib.parse import urlencode

import httpx

from truthnews.data import client

BASE = "https://api.gdeltproject.org/api/v2/doc/doc"
MIN_INTERVAL_S = 5.5  # GDELT pide como maximo una peticion cada 5 s
_last_call = 0.0


def timeline(
    query: str,
    timespan: str = "30d",
    transport: httpx.BaseTransport | None = None,
    sleep=time.sleep,
    retries: int = 2,
) -> list[dict]:
    """Serie diaria del porcentaje de cobertura mundial que menciona `query`."""
    global _last_call
    params = {"query": query, "mode": "timelinevol", "format": "json", "timespan": timespan}
    url = f"{BASE}?{urlencode(params)}"
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
        return []
    series = resp.json().get("timeline", [])
    return series[0].get("data", []) if series else []
