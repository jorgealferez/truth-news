"""Declaraciones de los partidos en sus canales oficiales verificados (ADR 0024).

Mismo cliente educado que el rastreador de medios (User-Agent propio, robots.txt, ritmo por dominio).
Un canal que responde 401/403 o que robots.txt prohibe no se lee: se cuenta y se sigue. Solo se guardan
el texto breve, el extracto y la URL para citarlo; lo que se muestra es la cita con enlace.

Del canal web se descarga ademas, una sola vez, el cuerpo del comunicado (ADR 0051): las cifras estan ahi y
no en el titular del RSS. Es para analisis interno, no se republica. Tope por ciclo y por dominio; un
dominio que responde 401/403 o que robots.txt prohibe se para y no se vuelve a pedir en BLOCK_HOURS.
"""

from __future__ import annotations

import asyncio
import calendar
import hashlib
import logging
import re
from datetime import UTC, datetime, timedelta
from html import unescape
from urllib.parse import quote, urlsplit

import feedparser
from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews.config import Settings
from truthnews.crawler import wikidata as wikidata_check
from truthnews.crawler.extract import extract_text
from truthnews.crawler.feeds import clean_text
from truthnews.crawler.http import PoliteClient
from truthnews.models import PoliticalStatement
from truthnews.registry import ActorSpec, ChannelSpec, load_political

log = logging.getLogger(__name__)

BSKY_API = "https://public.api.bsky.app/xrpc"
MAX_PER_CHANNEL = 20
TEXT_LIMIT = 600
BODY_LIMIT = 20_000  # caracteres del cuerpo guardado (ADR 0051)
BODIES_PER_CYCLE = 20
BODIES_PER_DOMAIN = 3
BODY_WINDOW_DAYS = 30  # la ventana que juzga analysis.statement_checks
BLOCK_HOURS = 24
BLOCKED = ("http 401", "http 403", "robots")


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


def _host(url: str) -> str:
    return urlsplit(url).netloc.lower()


def pending_bodies(session: Session, now: datetime, limit: int, per_domain: int) -> list[PoliticalStatement]:
    """Declaraciones del canal web sin intento de descarga, la mas reciente primero, con los topes; fuera
    los dominios que dieron 401/403 o robots.txt en las ultimas BLOCK_HOURS horas."""
    blocked = {
        _host(url)
        for url in session.scalars(
            select(PoliticalStatement.url).where(
                PoliticalStatement.body_status.in_(BLOCKED),
                PoliticalStatement.body_fetched_at >= now - timedelta(hours=BLOCK_HOURS),
            )
        )
    }
    rows = session.scalars(
        select(PoliticalStatement)
        .where(
            PoliticalStatement.channel == "web",
            PoliticalStatement.body_status.is_(None),
            PoliticalStatement.published_at >= now - timedelta(days=BODY_WINDOW_DAYS),
        )
        .order_by(PoliticalStatement.published_at.desc(), PoliticalStatement.id.desc())
    )
    out: list[PoliticalStatement] = []
    per: dict[str, int] = {}
    for st in rows:
        host = _host(st.url)
        if host in blocked or per.get(host, 0) >= per_domain:
            continue
        per[host] = per.get(host, 0) + 1
        out.append(st)
        if len(out) >= limit:
            break
    return out


async def _fetch_body(client: PoliteClient, url: str) -> tuple[str | None, str]:
    try:
        resp = await client.get(url)
        if resp is None:
            return None, "robots"
        if resp.status_code != 200:
            return None, f"http {resp.status_code}"
        text = await asyncio.to_thread(extract_text, resp.text, url)
    except Exception as exc:  # una pagina caida no tumba el resto
        return None, f"error {type(exc).__name__}"[:16]
    return (text[:BODY_LIMIT], "ok") if text else (None, "vacio")


async def _fetch_bodies(settings: Settings, rows: list[PoliticalStatement], transport) -> list[tuple]:
    """Por dominio, una tras otra: el que responde 401/403 o lo prohibe robots.txt se para ahi mismo."""
    by_host: dict[str, list[PoliticalStatement]] = {}
    for st in rows:
        by_host.setdefault(_host(st.url), []).append(st)

    async def host_rows(client: PoliteClient, sts: list[PoliticalStatement]) -> list[tuple]:
        out = []
        for st in sts:
            body, status = await _fetch_body(client, st.url)
            out.append((st, body, status))
            if status in BLOCKED:
                break  # el resto del dominio, sin intento: espera a que pasen BLOCK_HOURS
        return out

    async with PoliteClient(settings.user_agent, settings.per_domain_delay_seconds, transport=transport) as c:
        done = await asyncio.gather(*(host_rows(c, sts) for sts in by_host.values()))
    return [r for rs in done for r in rs]


def fetch_bodies(
    session: Session,
    settings: Settings,
    now: datetime | None = None,
    limit: int = BODIES_PER_CYCLE,
    per_domain: int = BODIES_PER_DOMAIN,
    transport=None,
) -> dict:
    """Descarga el cuerpo de los comunicados del canal web que aun no lo tienen (ADR 0051)."""
    now = now or datetime.now(UTC)
    rows = pending_bodies(session, now, limit, per_domain)
    out: dict = {"intentos": 0, "ok": 0, "estados": {}}
    for st, body, status in asyncio.run(_fetch_bodies(settings, rows, transport)) if rows else []:
        st.body, st.body_status, st.body_fetched_at = body, status, now
        out["intentos"] += 1
        out["ok"] += status == "ok"
        if status != "ok":
            out["estados"][status] = out["estados"].get(status, 0) + 1
    session.commit()
    return out


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
    try:
        out["bodies"] = fetch_bodies(session, settings)
    except Exception as exc:  # sin cuerpos se juzga con el extracto, como antes
        log.warning("declaraciones politicas: cuerpos fallidos: %s", exc)
        session.rollback()
        out["bodies"] = {"error": str(exc)[:300]}
    log.info("declaraciones politicas: %s", out)
    if wikidata:  # cuentas oficiales segun Wikidata, una vez por proceso, para revisar el registro
        try:
            out["wikidata"] = bool(wikidata_check.run_once(settings, actors))
        except Exception as exc:  # una consulta de cortesia caida no tumba la ingesta
            log.warning("wikidata: consulta fallida: %s", exc)
    return out
