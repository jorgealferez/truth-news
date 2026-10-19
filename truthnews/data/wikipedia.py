"""Wikipedia: contexto enciclopedico fechado para los hilos (antecedentes, no veredictos)."""

from __future__ import annotations

import httpx

from truthnews.data import client

API = "https://{lang}.wikipedia.org/w/api.php"


def search(
    query: str, lang: str = "es", limit: int = 3, transport: httpx.BaseTransport | None = None
) -> list[dict]:
    """Articulos que mejor responden a `query`, con su introduccion en texto plano y su URL."""
    params = {"action": "query", "list": "search", "srsearch": query, "srlimit": limit, "format": "json"}
    with client(transport) as c:
        resp = c.get(API.format(lang=lang), params=params)
        if resp.status_code != 200 or "json" not in resp.headers.get("content-type", ""):
            return []
        titles = [r["title"] for r in resp.json().get("query", {}).get("search", [])]
        if not titles:
            return []
        resp = c.get(
            API.format(lang=lang),
            params={
                "action": "query",
                "prop": "extracts",
                "exintro": 1,
                "explaintext": 1,
                "titles": "|".join(titles),
                "format": "json",
            },
        )
        if resp.status_code != 200 or "json" not in resp.headers.get("content-type", ""):
            return []
        pages = resp.json().get("query", {}).get("pages", {})
    by_title = {p.get("title"): p.get("extract", "") for p in pages.values()}
    return [
        {
            "title": t,
            "extract": " ".join(by_title.get(t, "").split())[:900],
            "url": f"https://{lang}.wikipedia.org/wiki/{t.replace(' ', '_')}",
        }
        for t in titles
        if by_title.get(t)
    ]
