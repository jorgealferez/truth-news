"""Piezas por red dentro de sus limites, en tono neutral y siempre con el enlace a nosmienten.com.

El texto se arma solo con datos (titular, cifras, veredicto, fuente): no hay adjetivos de cosecha propia.
Si no cabe, se quitan lineas de detalle desde el final y, en ultimo caso, se recorta el titular; el
enlace no se recorta nunca.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# (limite, coste fijo de una URL o None si cuenta su longitud real)
LIMITS = {
    "x": (280, 23),  # X cuenta cada enlace como 23 caracteres (t.co)
    "bluesky": (300, None),  # 300 grafemas; el enlace va en el texto con su faceta
    "mastodon": (500, 23),  # Mastodon cuenta cada enlace como 23
    "telegram": (1024, None),  # pie de foto de sendPhoto
}
_URL = re.compile(r"https?://\S+")


def length(network: str, text: str) -> int:
    """Longitud tal como la cuenta la red (aproximacion conservadora: puntos de codigo)."""
    _, url_cost = LIMITS[network]
    if url_cost is None:
        return len(text)
    return len(_URL.sub("", text)) + url_cost * len(_URL.findall(text))


@dataclass
class Draft:
    """Contenido de una pieza antes de ajustarlo a una red."""

    headline: str
    lines: list[str]
    cta: str  # "Datos y fuentes:", etc.
    url: str

    def render(self, headline: str, lines: list[str]) -> str:
        body = "\n".join(lines)
        return "\n\n".join(p for p in (headline, body, f"{self.cta} {self.url}") if p)


def fit(network: str, draft: Draft) -> str:
    limit, _ = LIMITS[network]
    lines = [ln for ln in draft.lines if ln]
    while True:
        text = draft.render(draft.headline, lines)
        if length(network, text) <= limit:
            return text
        if not lines:
            break
        lines = lines[:-1]
    # Solo queda recortar el titular, palabra a palabra.
    words = draft.headline.split()
    while words:
        words = words[:-1]
        text = draft.render(" ".join(words) + "…", [])
        if length(network, text) <= limit:
            return text
    return draft.render("", [])


def fmt(value: float) -> str:
    """Cifra al estilo espanol: 12.500; 3,4."""
    if float(value).is_integer():
        return f"{value:,.0f}".replace(",", ".")
    return f"{value:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def clip(text: str, n: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= n else text[: n - 1].rsplit(" ", 1)[0] + "…"
