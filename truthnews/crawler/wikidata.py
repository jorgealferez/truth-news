"""Cuentas oficiales de los partidos segun Wikidata, con el mismo metodo para todos (ADR 0024).

Solo se acepta la entidad cuya web oficial (P856) coincide con la del registro: asi un homonimo no se
cuela. El resultado se registra en el log para anadirlo al registro como dato revisado
(`verified: wikidata`); este modulo no guarda nada ni lee los canales que propone.
"""

from __future__ import annotations

import asyncio
import logging
from urllib.parse import quote, urlsplit

from truthnews.config import Settings
from truthnews.crawler.http import PoliteClient
from truthnews.registry import ActorSpec

log = logging.getLogger(__name__)

API = "https://www.wikidata.org/w/api.php"
ENTITY = "https://www.wikidata.org/wiki/Special:EntityData/{}.json"
PROPS = {
    "P856": "web",
    "P12361": "bluesky",
    "P4033": "mastodon",
    "P3789": "telegram",
    "P2397": "youtube",
    "P2002": "x",
}


class Stopped(RuntimeError):
    """robots.txt lo prohibe o Wikidata no responde 200: se para la consulta entera, sin reintentos."""


def host(url: str) -> str:
    h = urlsplit(url if "//" in url else f"https://{url}").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def claims(entity: dict, prop: str) -> list[str]:
    out = []
    for c in entity.get("claims", {}).get(prop, []):
        if c.get("rank") == "deprecated":
            continue
        value = c.get("mainsnak", {}).get("datavalue", {}).get("value")
        if isinstance(value, str):
            out.append(value)
    return out


async def _json(client: PoliteClient, url: str) -> dict | None:
    resp = await client.get(url)
    if resp is None:
        raise Stopped("robots.txt lo prohibe")  # no se elude: se deja escrito en el log
    if resp.status_code != 200:
        raise Stopped(f"HTTP {resp.status_code}")
    return resp.json()


async def channels_for(client: PoliteClient, actor: ActorSpec) -> dict | None:
    """La entidad de Wikidata cuya web oficial es la del registro, con sus cuentas; None si no hay."""
    found = await _json(
        client,
        f"{API}?action=wbsearchentities&search={quote(actor.full_name)}&language=es&type=item&limit=5&format=json",
    )
    want = host(actor.homepage)
    for hit in (found or {}).get("search", []):
        data = await _json(client, ENTITY.format(hit["id"]))
        entity = (data or {}).get("entities", {}).get(hit["id"], {})
        if want in {host(u) for u in claims(entity, "P856")}:
            out = {"qid": hit["id"]}
            out.update(
                {name: claims(entity, p) for p, name in PROPS.items() if p != "P856" and claims(entity, p)}
            )
            return out
    return None


async def collect(settings: Settings, actors: list[ActorSpec]) -> dict:
    out: dict = {}
    async with PoliteClient(settings.user_agent, max(settings.per_domain_delay_seconds, 1.0)) as client:
        for actor in actors:  # en serie y con ritmo: es una consulta de cortesia
            try:
                out[actor.slug] = await channels_for(client, actor)
            except Stopped as exc:
                out["_parado"] = f"{actor.slug}: {exc}"
                break
    return out


_DONE = False


def run_once(settings: Settings, actors: list[ActorSpec]) -> dict | None:
    """Una vez por proceso: el log del worker queda como evidencia para revisar el registro."""
    global _DONE
    if _DONE:
        return None
    _DONE = True
    out = asyncio.run(collect(settings, actors))
    log.info("wikidata: cuentas oficiales por partido: %s", out)
    return out
