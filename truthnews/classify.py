"""Clasificador ligero de categoria por pistas de URL, etiquetas del feed y lexico por idioma."""

from __future__ import annotations

import re
import unicodedata

from truthnews.registry import categories

DEFAULT_CATEGORY = "sociedad"
_WORD = re.compile(r"[\w']+", re.UNICODE)


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in text if not unicodedata.combining(ch))


def _contains(haystack: str, needle: str) -> bool:
    return re.search(r"(?<!\w)" + re.escape(needle) + r"(?!\w)", haystack) is not None


def classify(
    title: str,
    summary: str = "",
    url: str = "",
    tags: list[str] | None = None,
    language: str = "es",
    hint: str | None = None,
) -> str:
    """Devuelve el slug de categoria. Prioridad: opinion por URL > pista del feed > puntuacion."""
    cats = categories()
    url_n = normalize(url)
    path = re.sub(r"^https?://[^/]+", "", url_n)
    if any(f"/{h}" in path for h in cats["opinion"]["url_hints"]):
        return "opinion"
    if hint and hint in cats:
        return hint
    text = normalize(f"{title} {title} {summary} {' '.join(tags or [])}")
    scores: dict[str, float] = {}
    for slug, cat in cats.items():
        score = 0.0
        for h in cat.get("url_hints", []):
            if f"/{normalize(h)}" in path:
                score += 3
        for kw in cat.get("keywords", {}).get(language, []) or cat.get("keywords", {}).get("es", []):
            if _contains(text, normalize(kw)):
                score += 1
        for tag in tags or []:
            if normalize(tag) in (normalize(h) for h in cat.get("url_hints", [])):
                score += 2
        if score:
            scores[slug] = score
    if not scores:
        return DEFAULT_CATEGORY
    best = max(scores.values())
    return next(slug for slug in cats if scores.get(slug) == best)


def topics(title: str, tags: list[str] | None = None, limit: int = 6) -> list[str]:
    """Temas: etiquetas del feed normalizadas (las de mas valor editorial) sin duplicados."""
    out: list[str] = []
    for tag in tags or []:
        tag = tag.strip()
        if 2 < len(tag) <= 60 and tag.lower() not in (x.lower() for x in out):
            out.append(tag)
        if len(out) >= limit:
            break
    return out
