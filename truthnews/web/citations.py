"""Datos citados de una noticia y diferencias entre versiones (ADR 0003 y 0015).

Se cita por fragmentos: frases originales cortas que contienen una cifra, con enlace a la fuente, nunca
el texto completo del medio."""

from __future__ import annotations

import difflib
import re

from truthnews.analysis.compare import figures

MAX_CITES = 6
MAX_CITE_CHARS = 220
_SENTENCE = re.compile(r"(?<=[.!?…])\s+(?=[«\"“¿¡A-ZÁÉÍÓÚÑ0-9])")


def sentences(text: str | None) -> list[str]:
    text = " ".join((text or "").split())
    return [s.strip() for s in _SENTENCE.split(text) if s.strip()] if text else []


def cited_figures(article) -> list[dict]:
    """Frases del titular, el extracto y el texto que dan una cifra contable, sin repetir ninguna."""
    out, seen = [], set()
    for part in (article.title, article.summary, article.content_text):
        for sentence in sentences(part):
            key = sentence.lower()
            if key in seen:
                continue
            figs = figures(sentence)
            if not figs:
                continue
            seen.add(key)
            quote = (
                sentence if len(sentence) <= MAX_CITE_CHARS else sentence[: MAX_CITE_CHARS - 1].rstrip() + "…"
            )
            out.append({"quote": quote, "figures": [(noun, value, qual) for noun, value, qual, _ in figs]})
            if len(out) >= MAX_CITES:
                return out
    return out


def word_diff(before: str, after: str) -> list[tuple[str, str]]:
    """Segmentos ('=', '-', '+') palabra a palabra entre dos versiones."""
    a, b = before.split(), after.split()
    out: list[tuple[str, str]] = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(a=a, b=b, autojunk=False).get_opcodes():
        if op == "equal":
            out.append(("=", " ".join(a[i1:i2])))
            continue
        if i2 > i1:
            out.append(("-", " ".join(a[i1:i2])))
        if j2 > j1:
            out.append(("+", " ".join(b[j1:j2])))
    return out


def archive_url(article) -> str:
    """Copia de archivo publica mas cercana a la fecha de captura (Wayback Machine)."""
    return f"https://web.archive.org/web/{article.fetched_at:%Y%m%d%H%M%S}/{article.url}"


# Coberturas en directo: cambian el titular varias veces por hora y no son rectificaciones.
_LIVE = re.compile(
    r"(?:\ben (?:vivo|directo)\b|^\s*(?:directo|última hora|ultima hora|live)\s*[|:]|"
    r"[|:]\s*(?:directo|en directo|en vivo|live)\s*$|\bminuto a minuto\b|\blive (?:updates|blog)\b)",
    re.IGNORECASE,
)


def is_live(*texts: str | None) -> bool:
    """Si alguno de los textos (titular actual o versiones anteriores) es de una cobertura en directo."""
    return any(t and _LIVE.search(t) for t in texts)
