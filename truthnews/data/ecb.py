"""Banco Central Europeo (Data Portal, SDMX en JSON): series de tipos de interes como el Euribor."""

from __future__ import annotations

import httpx

from truthnews.data import Observation, client

BASE = "https://data-api.ecb.europa.eu/service/data"


def latest(
    flow: str, key: str, label: str = "", transport: httpx.BaseTransport | None = None
) -> Observation | None:
    """Ultimo valor de la serie `flow/key` con sus 14 periodos anteriores (los periodos son 'AAAA-MM')."""
    url = f"{BASE}/{flow}/{key}?lastNObservations=14&format=jsondata"
    with client(transport) as c:
        resp = c.get(url)
    if resp.status_code != 200:
        return None
    body = resp.json()
    try:
        obs = next(iter(body["dataSets"][0]["series"].values()))["observations"]
        periods = body["structure"]["dimensions"]["observation"][0]["values"]
    except (KeyError, IndexError, StopIteration):
        return None
    points = sorted((periods[int(i)]["id"], float(v[0])) for i, v in obs.items() if v and v[0] is not None)
    if not points:
        return None
    page = f"https://data.ecb.europa.eu/data/datasets/{flow}/{flow}.{key}"
    prev = Observation("ecb", label, page, points[-2][0], points[-2][1]) if len(points) > 1 else None
    return Observation(
        "ecb",
        label,
        page,
        points[-1][0],
        points[-1][1],
        previous=prev,
        extra={"serie_bce": key},
        history=dict(points),
    )
