"""BOE, legislacion consolidada (API de datos abiertos): normas por palabras del titulo y fechas.

Sirve para buscar, con fecha y enlace, normas del Estado sobre lo que alguien prometio (ADR 0040). Solo
titulos y metadatos oficiales; nada se interpreta aqui.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date

import httpx

from truthnews.data import client

API = "https://www.boe.es/datosabiertos/api/legislacion-consolidada"
# Rangos con fuerza de ley o reglamento general del Estado: lo que puede cumplir un compromiso de gobierno.
RANKS = ("Ley Orgánica", "Ley", "Real Decreto-ley", "Real Decreto Legislativo", "Real Decreto")


@dataclass(frozen=True)
class Norm:
    id: str
    title: str
    rank: str
    published: date
    url: str


def query_for(terms: list[str], since: date, until: date) -> str:
    words = " OR ".join(t.replace('"', "") for t in terms)
    return json.dumps(
        {
            "query": {
                "query_string": {"query": f"titulo:({words})"},
                "range": {"fecha_publicacion": {"gte": f"{since:%Y%m%d}", "lte": f"{until:%Y%m%d}"}},
            },
            "sort": [{"fecha_publicacion": "desc"}],
        }
    )


def parse(payload: dict) -> list[Norm]:
    out = []
    for x in payload.get("data") or []:
        rank = (x.get("rango") or {}).get("texto", "")
        if (x.get("ambito") or {}).get("texto") != "Estatal" or rank not in RANKS:
            continue
        raw = x.get("fecha_publicacion") or ""
        try:
            published = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        except ValueError:
            continue
        out.append(
            Norm(
                id=x.get("identificador", ""),
                title=x.get("titulo", ""),
                rank=rank,
                published=published,
                url=x.get("url_html_consolidada") or x.get("url_eli") or "",
            )
        )
    return out


def search(
    terms: list[str], since: date, until: date, limit: int = 50, transport: httpx.BaseTransport | None = None
) -> list[Norm]:
    """Normas estatales publicadas entre `since` y `until` cuyo titulo contiene alguno de los `terms`."""
    if not terms:
        return []
    with client(transport) as c:
        resp = c.get(
            API,
            params={"query": query_for(terms, since, until), "limit": str(limit)},
            headers={"Accept": "application/json"},
        )
    if resp.status_code != 200:
        raise httpx.HTTPError(f"BOE legislacion {resp.status_code}")
    return parse(resp.json())
