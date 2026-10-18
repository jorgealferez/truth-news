"""Eurostat (API de difusion JSON-stat 2.0): series de la UE por pais."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from truthnews.data import Observation, client

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
# Codigos de Eurostat. Los agregados cambian con las adhesiones: se prueban en orden (EA21 desde 2026).
_GEO = {"GR": ["EL"], "EU": ["EU27_2020"], "EA": ["EA21", "EA20", "EA19"]}


def latest(
    dataset: str, geo: str, params: dict, label: str = "", transport: httpx.BaseTransport | None = None
) -> Observation | None:
    """Ultima observacion no vacia (y la anterior) de una serie unidimensional."""
    for code in _GEO.get(geo, [geo]):
        obs = _latest(dataset, geo, code, params, label, transport)
        if obs is not None:
            return obs
    return None


def _latest(
    dataset: str, geo: str, code: str, params: dict, label: str, transport: httpx.BaseTransport | None
) -> Observation | None:
    query = {**params, "geo": code, "lastTimePeriod": 14}
    url = f"{BASE}/{dataset}?{urlencode(query)}"
    with client(transport) as c:
        resp = c.get(url)
    if resp.status_code != 200:
        return None
    data = resp.json()
    if "value" not in data or "dimension" not in data:
        return None
    index = data["dimension"]["time"]["category"]["index"]
    by_pos = {pos: period for period, pos in index.items()}
    sizes = data["size"]
    time_size = sizes[data["id"].index("time")]
    if any(s != 1 for d, s in zip(data["id"], sizes, strict=True) if d != "time"):
        return None  # la consulta no fijo todas las dimensiones: ambiguo, no se usa
    points = sorted(
        ((by_pos[int(k) % time_size], float(v)) for k, v in data["value"].items() if v is not None),
        key=lambda x: x[0],
    )
    if not points:
        return None
    period, value = points[-1]
    prev = None
    if len(points) > 1:
        prev = Observation("eurostat", label, url, points[-2][0], points[-2][1])
    return Observation(
        "eurostat",
        label or data.get("label", dataset),
        url,
        period,
        value,
        previous=prev,
        extra={"dataset": dataset, "updated": data.get("updated"), "geo": geo},
        history=dict(points),
    )
