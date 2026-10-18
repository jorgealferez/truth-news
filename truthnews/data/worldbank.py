"""Banco Mundial (API v2): indicadores anuales de cualquier pais."""

from __future__ import annotations

import httpx

from truthnews.data import Observation, client

BASE = "https://api.worldbank.org/v2"


def latest(
    indicator: str, geo: str, label: str = "", transport: httpx.BaseTransport | None = None
) -> Observation | None:
    geo = "EUU" if geo == "EU" else geo
    url = f"{BASE}/country/{geo}/indicator/{indicator}?format=json&mrv=6"
    with client(transport) as c:
        resp = c.get(url)
    if resp.status_code != 200:
        return None
    body = resp.json()
    if not isinstance(body, list) or len(body) < 2 or not body[1]:
        return None
    points = sorted((r["date"], float(r["value"])) for r in body[1] if r.get("value") is not None)
    if not points:
        return None
    name = body[1][0]["indicator"]["value"]
    prev = None
    if len(points) > 1:
        prev = Observation("worldbank", label or name, url, points[-2][0], points[-2][1])
    return Observation(
        "worldbank",
        label or name,
        url,
        points[-1][0],
        points[-1][1],
        previous=prev,
        extra={"indicator": indicator, "geo": geo},
    )
