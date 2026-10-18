"""Eurostat (API de difusion JSON-stat 2.0): series de la UE por pais."""

from __future__ import annotations

from urllib.parse import urlencode

import httpx

from truthnews.data import Observation, client

BASE = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data"
_GEO = {"GR": "EL", "EU": "EU27_2020"}


def latest(
    dataset: str, geo: str, params: dict, label: str = "", transport: httpx.BaseTransport | None = None
) -> Observation | None:
    """Ultima observacion no vacia (y la anterior) de una serie unidimensional."""
    query = {**params, "geo": _GEO.get(geo, geo), "lastTimePeriod": 8}
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
    )
