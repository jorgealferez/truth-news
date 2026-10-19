"""Mide en vivo el enlace de historias con medios de otros paises (ADR 0022) para etiquetarlo a mano.

Agrupa los titulares de los medios espanoles (historias de >= 3 medios) y los enlaza con los de medios
hispanohablantes de otros paises; imprime cada enlace con su similitud. Sin IA: solo titulares en espanol.
Uso: python tools/eval_abroad.py [umbral]
"""

from __future__ import annotations

import asyncio
import json
import sys

from truthnews.analysis import abroad
from truthnews.analysis.cluster import Doc, cluster
from truthnews.config import get_settings
from truthnews.crawler.feeds import parse_feed
from truthnews.crawler.http import PoliteClient
from truthnews.registry import load_outlets


async def fetch(client, o, url):
    try:
        r = await client.get(url)
        if r is None or r.status_code != 200:
            return []
        return [(o, e) for e in parse_feed(r.content)[0]]
    except Exception:
        return []


async def main():
    s = get_settings()
    outs = [o for o in load_outlets() if o.feeds and (o.country == "ES" or o.language == "es")]
    async with PoliteClient(s.user_agent, s.per_domain_delay_seconds) as c:
        res = await asyncio.gather(*(fetch(c, o, f.url) for o in outs for f in o.feeds[:1]))
    es, foreign = [], []
    for o, e in (x for r in res for x in r):
        d = Doc(key=e.url, title=e.title, summary=e.summary or "", published_at=e.published_at, outlet=o.slug)
        (es if o.country == "ES" else foreign).append((d, o))
    groups = [g for g in cluster([d for d, _ in es]) if len({m.outlet for m in g.members}) >= 3]
    stories = {i: [m.title for m in g.members] for i, g in enumerate(groups)}
    fmap = {d.key: (d, o) for d, o in foreign}
    links = abroad.match(
        stories,
        [(d, o.country) for d, o in foreign],
        threshold=float(sys.argv[1]) if len(sys.argv) > 1 else abroad.THRESHOLD,
    )
    print(
        json.dumps(
            {
                "es_articles": len(es),
                "foreign_es_articles": len(foreign),
                "stories_3plus": len(groups),
                "stories_linked": len(links),
            }
        )
    )
    for sid, picked in links.items():
        print("\n##", stories[sid][0])
        for key, sim in picked:
            d, o = fmap[key]
            print(f"   {sim:.2f} [{o.country} {o.slug}] {d.title}")


if __name__ == "__main__":
    asyncio.run(main())
