"""BOE (API de datos abiertos): sumario diario para comprobar que una norma se publico."""

from __future__ import annotations

from datetime import date

import httpx

from truthnews.analysis.text import tokens
from truthnews.data import client

BASE = "https://www.boe.es/datosabiertos/api/boe/sumario"


def sumario(day: date, transport: httpx.BaseTransport | None = None) -> list[dict]:
    url = f"{BASE}/{day:%Y%m%d}"
    with client(transport) as c:
        resp = c.get(url, headers={"Accept": "application/json"})
    if resp.status_code != 200:
        return []
    items: list[dict] = []

    def walk(node):
        if isinstance(node, dict):
            if "titulo" in node and "identificador" in node:
                url_html = node.get("url_html") or node.get("url_pdf", {})
                items.append(
                    {
                        "id": node["identificador"],
                        "titulo": node["titulo"],
                        "url": url_html if isinstance(url_html, str) else url_html.get("texto", ""),
                    }
                )
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(resp.json().get("data", {}))
    return items


def search(
    day: date, text: str, min_overlap: float = 0.5, transport: httpx.BaseTransport | None = None
) -> list[dict]:
    """Disposiciones del dia cuyo titulo comparte al menos `min_overlap` de los terminos del texto."""
    wanted = set(tokens(text))
    if not wanted:
        return []
    hits = []
    for item in sumario(day, transport=transport):
        overlap = len(wanted & set(tokens(item["titulo"]))) / len(wanted)
        if overlap >= min_overlap:
            hits.append({**item, "overlap": round(overlap, 2)})
    return sorted(hits, key=lambda h: -h["overlap"])
