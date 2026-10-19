"""Distribucion (Fase 4 parcial): imagen social por historia, enlaces para compartir, sitemap y RSS.

La imagen se dibuja con Pillow y la fuente Inter (subconjunto latino, OFL 1.1, en `web/fonts`), y se
cachea en memoria por historia y fecha de actualizacion: X, Facebook, WhatsApp o Telegram la piden una
vez por enlace compartido.
"""

from __future__ import annotations

import io
from datetime import datetime
from functools import lru_cache
from pathlib import Path
from urllib.parse import quote
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

FONTS = Path(__file__).resolve().parent / "fonts"
INK, PAPER, AMBER, MUTED, BAR = "#14161b", "#fbfaf6", "#e8a317", "#595959", "#f6e2b3"
VERDICT_COLORS = {
    "verdadero": "#1b7a3a",
    "impreciso": "#b07300",
    "falso": "#b3001b",
    "enganoso": "#7a2a8c",
    "sin-datos": "#6b6b6b",
}


@lru_cache(maxsize=8)
def _font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Inter-{weight}.otf"), size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, width: int, max_lines: int) -> list[str]:
    lines: list[str] = []
    for word in text.split():
        if lines and draw.textlength(f"{lines[-1]} {word}", font=font) <= width:
            lines[-1] = f"{lines[-1]} {word}"
        else:
            lines.append(word)
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        while draw.textlength(lines[-1] + "…", font=font) > width and " " in lines[-1]:
            lines[-1] = lines[-1].rsplit(" ", 1)[0]
        lines[-1] += "…"
    return lines


def _mark(draw: ImageDraw.ImageDraw, x: int, y: int, size: int) -> None:
    """El simbolo (ADR 0014, la "n medida") sobre una placa de papel: el arco de la n baja hasta una vara
    ambar graduada. Misma geometria que `mark.svg`, en una rejilla de 64."""

    def box(x0: float, y0: float, x1: float, y1: float) -> tuple[float, float, float, float]:
        return (x + x0 * s, y + y0 * s, x + x1 * s, y + y1 * s)

    s = size / 64
    draw.rounded_rectangle(box(0, 0, 64, 64), radius=14 * s, fill=PAPER)
    draw.pieslice(box(12, 10, 52, 50), 180, 360, fill=INK)
    draw.pieslice(box(22, 20, 42, 40), 180, 360, fill=PAPER)
    draw.rectangle(box(12, 30, 22, 54), fill=INK)
    draw.rectangle(box(42, 32.4, 52, 54), fill=AMBER)
    for ty, w in ((35.6, 5.2), (39.4, 3), (43.2, 5.2), (47, 3), (50.8, 5.2)):
        draw.rectangle(box(42, ty, 42 + w, ty + 1.5), fill=PAPER)


def _wordmark(draw: ImageDraw.ImageDraw, x: float, baseline: float, size: int) -> None:
    """"nos" + "mienten" + ".com" como en `logo.svg`, en papel sobre tinta: la i de "mienten" lleva una marca
    cuadrada ambar en lugar del punto (ADR 0014)."""
    nos, bold = _font("Medium", size), _font("ExtraBold", size)
    draw.text((x, baseline), "nos", font=nos, fill=PAPER, anchor="ls")
    x += draw.textlength("nos", font=nos)
    draw.text((x, baseline), "m\u0131enten", font=bold, fill=PAPER, anchor="ls")
    dot_x, top, side = (v * size / 2048 for v in (115, 1585, 349))
    left = x + draw.textlength("m", font=bold) + dot_x
    draw.rectangle((left, baseline - top, left + side, baseline - top + side), fill=AMBER)
    x += draw.textlength("m\u0131enten", font=bold)
    draw.text((x, baseline), ".com", font=nos, fill=AMBER, anchor="ls")


def _ruler(draw: ImageDraw.ImageDraw, x0: int, x1: int, y: int, step: int) -> None:
    """La regla de la marca: marcas cortas cada `step` y largas cada cinco."""
    draw.rectangle((x0, y, x1, y + 1), fill=INK)
    for i, x in enumerate(range(x0, x1 + 1, step)):
        draw.rectangle((x, y + 2, x + 1, y + (13 if i % 5 == 0 else 7)), fill=INK)


def story_image(
    title: str,
    kicker: str,
    disputes: list[tuple[str, float, float, int]],
    verdicts: dict[str, int],
    footer: str,
) -> bytes:
    """PNG 1200x630: titular, cifras en disputa (sustantivo, minimo, maximo, medios) y veredictos."""
    img = Image.new("RGB", (1200, 630), PAPER)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, 1200, 84), fill=INK)
    _mark(d, 48, 18, 48)
    _wordmark(d, 112, 54, 34)
    d.text((48, 112), kicker.upper(), font=_font("ExtraBold", 22), fill="#8a5a00")
    y = 146
    has_marks = bool(disputes or verdicts)
    for line in _wrap(d, title, _font("ExtraBold", 50), 1104, 3 if has_marks else 5):
        d.text((48, y), line, font=_font("ExtraBold", 50), fill=INK)
        y += 60
    y += 18
    for noun, low, high, n in disputes[:2]:
        label = f"{noun.capitalize()}: de {low:,.0f} a {high:,.0f}".replace(",", ".")
        d.text((48, y), label, font=_font("ExtraBold", 30), fill=INK)
        d.text(
            (48 + d.textlength(label, font=_font("ExtraBold", 30)) + 14, y + 4),
            f"según {n} medios",
            font=_font("Medium", 24),
            fill=MUTED,
        )
        d.rounded_rectangle(
            (48, y + 42, 48 + 700 * (low / high if high else 1), y + 52), radius=5, fill=AMBER
        )
        d.rounded_rectangle((48, y + 58, 748, y + 68), radius=5, fill=INK)
        y += 86
    if verdicts:
        total, x = sum(verdicts.values()), 48
        for k, n in verdicts.items():
            w = int(700 * n / total)
            d.rectangle((x, y, x + w, y + 22), fill=VERDICT_COLORS.get(k, MUTED))
            x += w
        y += 34
    _ruler(d, 48, 1152, 548, 16)
    d.rectangle((0, 576, 1200, 630), fill=INK)
    d.text((48, 590), footer, font=_font("Medium", 24), fill=PAPER)
    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def share_links(url: str, text: str) -> list[tuple[str, str, str]]:
    """(id, nombre, enlace) de cada red; sin scripts de terceros ni rastreadores."""
    u, t = quote(url, safe=""), quote(text, safe="")
    return [
        ("whatsapp", "WhatsApp", f"https://wa.me/?text={t}%20{u}"),
        ("x", "X", f"https://x.com/intent/post?text={t}&url={u}"),
        ("telegram", "Telegram", f"https://t.me/share/url?url={u}&text={t}"),
        ("facebook", "Facebook", f"https://www.facebook.com/sharer/sharer.php?u={u}"),
        ("bluesky", "Bluesky", f"https://bsky.app/intent/compose?text={t}%20{u}"),
        ("linkedin", "LinkedIn", f"https://www.linkedin.com/sharing/share-offsite/?url={u}"),
        ("email", "Email", f"mailto:?subject={t}&body={u}"),
    ]


def sitemap_xml(urls: list[tuple[str, datetime | None]]) -> str:
    rows = []
    for loc, lastmod in urls:
        mod = f"<lastmod>{lastmod:%Y-%m-%d}</lastmod>" if lastmod else ""
        rows.append(f"<url><loc>{escape(loc)}</loc>{mod}</url>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + "".join(rows) + "</urlset>\n"
    )


def rss_xml(title: str, link: str, description: str, items: list[dict]) -> str:
    """RSS 2.0; cada item: title, link, description, date (datetime con zona)."""
    body = "".join(
        "<item>"
        f"<title>{escape(i['title'])}</title><link>{escape(i['link'])}</link>"
        f'<guid isPermaLink="true">{escape(i["link"])}</guid>'
        f"<description>{escape(i['description'])}</description>"
        f"<pubDate>{i['date']:%a, %d %b %Y %H:%M:%S +0000}</pubDate>"
        "</item>"
        for i in items
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n<rss version="2.0"><channel>'
        f"<title>{escape(title)}</title><link>{escape(link)}</link>"
        f"<description>{escape(description)}</description><language>es</language>{body}</channel></rss>\n"
    )
