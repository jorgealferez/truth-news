"""Descubrimiento y parseo de feeds RSS/Atom."""

from __future__ import annotations

import calendar
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from html import unescape
from urllib.parse import urljoin

import feedparser

FEED_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/feed+json",
    "application/xml",
    "text/xml",
)
_LINK_RE = re.compile(r"<link\b[^>]*>", re.IGNORECASE)
_ATTR_RE = re.compile(r"""(\w[\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s>]+))""")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_CDATA_RE = re.compile(r"<!\[CDATA\[(.*?)\]\]>", re.DOTALL)


def discover_feed_urls(html: str, base_url: str, limit: int = 4) -> list[str]:
    """Feeds anunciados en la portada con <link rel="alternate" type="application/rss+xml">."""
    found: list[str] = []
    for tag in _LINK_RE.findall(html):
        attrs = {
            m.group(1).lower(): (m.group(2) or m.group(3) or m.group(4) or "") for m in _ATTR_RE.finditer(tag)
        }
        rel = attrs.get("rel", "").lower().split()
        if "alternate" not in rel or attrs.get("type", "").lower() not in FEED_TYPES or not attrs.get("href"):
            continue
        href = urljoin(base_url, unescape(attrs["href"]))
        if "comment" in href.lower():
            continue
        if href not in found:
            found.append(href)
        if len(found) >= limit:
            break
    return found


def clean_text(html: str | None, limit: int | None = None) -> str:
    if not html:
        return ""
    # Algunos feeds escapan el CDATA dentro del titulo: se desenvuelve antes de quitar etiquetas.
    html = _CDATA_RE.sub(r"\1", html)
    text = _WS_RE.sub(" ", unescape(_TAG_RE.sub(" ", html))).strip()
    if limit and len(text) > limit:
        text = text[: limit - 1].rsplit(" ", 1)[0] + "…"
    return text


@dataclass
class FeedEntry:
    url: str
    title: str
    summary: str = ""
    author: str | None = None
    published_at: datetime | None = None
    tags: list[str] = field(default_factory=list)
    image_url: str | None = None


def _entry_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed", "created_parsed"):
        value = entry.get(key)
        if value:
            return datetime.fromtimestamp(calendar.timegm(value), UTC)
    return None


def _entry_image(entry) -> str | None:
    for media in entry.get("media_content", []) + entry.get("media_thumbnail", []):
        if media.get("url"):
            return media["url"]
    for enc in entry.get("enclosures", []):
        if enc.get("type", "").startswith("image") and enc.get("href"):
            return enc["href"]
    return None


def parse_feed(content: bytes | str, limit: int = 30) -> tuple[list[FeedEntry], bool]:
    """Devuelve (entradas, es_feed). `es_feed` es False si el contenido no parece RSS/Atom."""
    parsed = feedparser.parse(content)
    is_feed = bool(parsed.get("version")) or bool(parsed.entries)
    entries: list[FeedEntry] = []
    for entry in parsed.entries[:limit]:
        link = entry.get("link")
        title = clean_text(entry.get("title"))
        if not link or not title:
            continue
        entries.append(
            FeedEntry(
                url=link.strip(),
                title=title[:600],
                summary=clean_text(entry.get("summary") or entry.get("description"), limit=1200),
                # Las columnas tienen tope (author 300, image_url 1000): un valor largo tumbaria el rastreo.
                author=(clean_text(entry.get("author"))[:300] or None),
                published_at=_entry_date(entry),
                tags=[t.get("term", "").strip() for t in entry.get("tags", []) if t.get("term")],
                image_url=(_entry_image(entry) or "")[:1000] or None,
            )
        )
    return entries, is_feed
