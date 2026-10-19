"""Declaraciones de los partidos en sus canales oficiales verificados (ADR 0024).

Mismo cliente educado que el rastreador de medios (User-Agent propio, robots.txt, ritmo por dominio).
Un canal que responde 401/403 o que robots.txt prohibe no se lee: se cuenta y se sigue. Solo se guardan
el texto breve, el extracto y la URL para citarlo; lo que se muestra es la cita con enlace.
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import logging
import re
from datetime import UTC, datetime
from html import unescape
from urllib.parse import quote

import feedparser
from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews.config import Settings
from truthnews.crawler import wikidata as wikidata_check
from truthnews.crawler.feeds import clean_text
from truthnews.crawler.http import PoliteClient
from truthnews.models import PoliticalStatement
from truthnews.registry import ActorSpec, ChannelSpec, load_political

log = logging.getLogger(__name__)

BSKY_API = "https://public.api.bsky.app/xrpc"
MAX_PER_CHANNEL = 20
TEXT_LIMIT = 600


def _short(text: str) -> str:
    text = clean_text(text) or ""
    return text if len(text) <= 280 else text[:277].rsplit(" ", 1)[0] + "…"


def _date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def parse_rss(content: bytes | str) -> list[dict]:
    """RSS/Atom de una web o de un perfil de Mastodon: los posts sociales no traen titulo, solo texto."""
    out = []
    for e in feedparser.parse(content).entries[:MAX_PER_CHANNEL]:
        link = e.get("link")
        body = clean_text(e.get("summary") or e.get("description"), limit=1200)
        text = clean_text(e.get("title")) or _short(body or "")
        stamp = e.get("published_parsed") or e.get("updated_parsed")
        if not link or not text or not stamp:
            continue
        published = datetime.fromtimestamp(calendar.timegm(stamp), tz=UTC)
        out.append({"url": link.strip(), "text": text, "summary": body, "published_at": published})
    return out


def parse_bluesky(data: dict, handle: str) -> list[dict]:
    out = []
    for item in data.get("feed", [])[:MAX_PER_CHANNEL]:
        post = item.get("post") or {}
        if item.get("reason"):  # una republicacion no es una declaracion propia
            continue
        record = post.get("record") or {}
        text, uri = record.get("text") or "", post.get("uri") or ""
        published = _date(record.get("createdAt"))
        if not text.strip() or not uri or published is None:
            continue
        rkey = uri.rsplit("/", 1)[-1]
        out.append(
            {
                "url": f"https://bsky.app/profile/{handle}/post/{rkey}",
                "text": _short(text),
                "summary": clean_text(text, limit=1200),
                "published_at": published,
            }
        )
    return out


_TG_TEXT = re.compile(r'class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>', re.S)
_TG_TIME = re.compile(r'<time datetime="([^"]+)"')


def parse_telegram(html: str, handle: str) -> list[dict]:
    """Vista publica de un canal (t.me/s/<canal>): mensaje, enlace permanente y fecha."""
    out = []
    for part in html.split('data-post="')[1:]:
        post_id = part.split('"', 1)[0]
        if not post_id.lower().startswith(handle.lower() + "/"):
            continue  # mensajes reenviados de otros canales
        m, t = _TG_TEXT.search(part), _TG_TIME.search(part)
        if not m or not t:
            continue
        raw = re.sub(r"<br\s*/?>", " ", m.group(1))
        text = clean_text(unescape(re.sub(r"<[^>]+>", " ", raw)), limit=1200)
        published = _date(t.group(1))
        if not text or published is None:
            continue
        out.append(
            {
                "url": f"https://t.me/{post_id}",
                "text": _short(text),
                "summary": text,
                "published_at": published,
            }
        )
    return out[-MAX_PER_CHANNEL:]


async def fetch_channel(client: PoliteClient, ch: ChannelSpec) -> tuple[list[dict], str]:
    """Devuelve (entradas, estado). Estado: ok, robots, http <codigo> o error."""
    try:
        if ch.channel == "bluesky":
            url = f"{BSKY_API}/app.bsky.feed.getAuthorFeed?actor={quote(ch.handle)}&limit=30"
            url += "&filter=posts_no_replies"
        elif ch.channel == "telegram":
            url = f"https://t.me/s/{quote(ch.handle)}"
        else:
            url = ch.url
        resp = await client.get(url)
        if resp is None:
            return [], "robots"
        if resp.status_code != 200:
            return [], f"http {resp.status_code}"
        if ch.channel == "bluesky":
            return parse_bluesky(resp.json(), ch.handle), "ok"
        if ch.channel == "telegram":
            return parse_telegram(resp.text, ch.handle), "ok"
        return parse_rss(resp.content), "ok"
    except Exception as exc:  # un canal caido no tumba el resto
        return [], f"error {type(exc).__name__}"


def store(session: Session, actor: ActorSpec, channel: str, items: list[dict]) -> int:
    hashes = {hashlib.sha256(i["url"].encode()).hexdigest(): i for i in items}
    known = set(
        session.scalars(select(PoliticalStatement.url_hash).where(PoliticalStatement.url_hash.in_(hashes)))
    )
    new = 0
    for h, i in hashes.items():
        if h in known:
            continue
        session.add(
            PoliticalStatement(
                actor=actor.slug,
                country=actor.country,
                channel=channel,
                url=i["url"][:1000],
                url_hash=h,
                text=i["text"][:TEXT_LIMIT],
                summary=i.get("summary"),
                published_at=i["published_at"],
            )
        )
        new += 1
    return new


async def collect(
    settings: Settings, actors: list[ActorSpec]
) -> list[tuple[ActorSpec, ChannelSpec, list, str]]:
    targets = [(a, ch) for a in actors for ch in a.channels]
    async with PoliteClient(settings.user_agent, settings.per_domain_delay_seconds) as client:
        results = await asyncio.gather(*(fetch_channel(client, ch) for _, ch in targets))
    return [(a, ch, items, status) for (a, ch), (items, status) in zip(targets, results, strict=True)]


def run(
    session: Session, settings: Settings, actors: list[ActorSpec] | None = None, wikidata: bool = False
) -> dict:
    actors = actors if actors is not None else load_political()
    out: dict = {"channels": 0, "channels_ok": 0, "new": 0, "failed": {}}
    for actor, ch, items, status in asyncio.run(collect(settings, actors)):
        out["channels"] += 1
        if status != "ok":
            out["failed"][f"{actor.slug}:{ch.channel}:{ch.url or ch.handle}"] = status
            continue
        out["channels_ok"] += 1
        out["new"] += store(session, actor, ch.channel, items)
    session.commit()
    log.info("declaraciones politicas: %s", out)
    if wikidata:  # cuentas oficiales segun Wikidata, una vez por proceso, para revisar el registro
        try:
            out["wikidata"] = bool(wikidata_check.run_once(settings, actors))
        except Exception as exc:  # una consulta de cortesia caida no tumba la ingesta
            log.warning("wikidata: consulta fallida: %s", exc)
    return out
