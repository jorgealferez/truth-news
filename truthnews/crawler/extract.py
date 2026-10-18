"""Extraccion del texto principal de un articulo (para analisis interno, no para republicar)."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import trafilatura

_TRACKING = re.compile(r"^(utm_|fbclid|gclid|mc_|ref$|ns_|_ga)")


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if not _TRACKING.match(k)]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path, urlencode(query), ""))


def sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def extract_text(html: str, url: str | None = None) -> str | None:
    text = trafilatura.extract(
        html, url=url, include_comments=False, include_tables=False, favor_precision=True
    )
    return text.strip() if text else None


def word_count(text: str | None) -> int:
    return len(text.split()) if text else 0
