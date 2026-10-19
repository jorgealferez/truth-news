"""Mide en vivo los feeds del registro por pais (criterio C10): validos, entradas y bloqueos.

Usa el mismo cliente educado que el rastreador (User-Agent propio, robots.txt, ritmo por dominio).
Uso: python tools/check_feeds.py [ISO ...]   -> JSON con el resumen por pais y los feeds que fallan.
"""

from __future__ import annotations

import asyncio
import json
import sys

from truthnews.config import get_settings
from truthnews.crawler.feeds import parse_feed
from truthnews.crawler.http import PoliteClient
from truthnews.registry import load_outlets


async def _check(client: PoliteClient, url: str) -> dict:
    try:
        resp = await client.get(url)
    except Exception as exc:  # se informa, no se oculta
        return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]}
    if resp is None:
        return {"ok": False, "error": "robots.txt lo prohibe"}
    if resp.status_code != 200:
        return {"ok": False, "error": f"HTTP {resp.status_code}"}
    entries, is_feed = parse_feed(resp.content)
    if not is_feed or not entries:
        return {"ok": False, "error": "no es un feed o esta vacio"}
    return {"ok": True, "entries": len(entries)}


async def main(countries: set[str]) -> dict:
    settings = get_settings()
    outlets = [o for o in load_outlets() if not countries or o.country in countries]
    targets = [(o, f.url) for o in outlets for f in o.feeds]
    async with PoliteClient(settings.user_agent, settings.per_domain_delay_seconds) as client:
        results = await asyncio.gather(*(_check(client, url) for _, url in targets))
    summary: dict = {}
    failing = []
    for (outlet, url), res in zip(targets, results, strict=True):
        row = summary.setdefault(
            outlet.country, {"outlets": 0, "feeds": 0, "feeds_ok": 0, "entries": 0, "languages": set()}
        )
        row["feeds"] += 1
        row["languages"].add(outlet.language)
        if res["ok"]:
            row["feeds_ok"] += 1
            row["entries"] += res["entries"]
        else:
            failing.append({"outlet": outlet.slug, "url": url, "error": res["error"]})
    for outlet in outlets:
        summary.setdefault(
            outlet.country, {"outlets": 0, "feeds": 0, "feeds_ok": 0, "entries": 0, "languages": set()}
        )["outlets"] += 1
    for row in summary.values():
        row["languages"] = sorted(row["languages"])
    return {"by_country": dict(sorted(summary.items())), "failing": failing}


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main(set(sys.argv[1:]))), ensure_ascii=False, indent=1))
