"""Genera los PNG de la marca (ADR 0011) a partir de la geometria de `mark.svg`.

Uso: python tools/brand.py  (necesita Pillow, fontTools y la fuente Inter, OFL 1.1; solo en desarrollo)
Escribe en truthnews/web/static/: logo.svg (marca + nombre en contornos, no depende de las fuentes del
lector), icon-180.png, icon-192.png, icon-512.png, favicon.ico y og-default.png (1200x630, imagen por
defecto para redes sociales).
"""

from __future__ import annotations

from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

STATIC = Path(__file__).resolve().parents[1] / "truthnews" / "web" / "static"
INK, PAPER, AMBER, MUTED, AMBER_TEXT = "#14161b", "#fbfaf6", "#e8a317", "#5b5b5b", "#8a5a00"
FONTS = Path("/usr/share/fonts/opentype/inter")


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Inter-{weight}.otf"), size)


def mark(size: int) -> Image.Image:
    """La marca en un cuadrado de `size` px: dos barras, la de abajo mas corta (lo que se cuenta y lo que
    dicen los datos no siempre miden lo mismo)."""
    s = size / 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=14 * s, fill=INK)
    d.rounded_rectangle((13 * s, 20 * s, 51 * s, 28 * s), radius=4 * s, fill=PAPER)
    d.rounded_rectangle((13 * s, 36 * s, 35 * s, 44 * s), radius=4 * s, fill=AMBER)
    return img


def og() -> Image.Image:
    img = Image.new("RGB", (1200, 630), PAPER)
    d = ImageDraw.Draw(img)
    img.paste(mark(150), (90, 150), mark(150))
    x = 272
    nos, mienten = font("Medium", 96), font("ExtraBold", 96)
    d.text((x, 150), "nos", font=nos, fill=INK)
    x2 = x + d.textlength("nos", font=nos)
    d.text((x2, 150), "mienten", font=mienten, fill=INK)
    x3 = x2 + d.textlength("mienten", font=mienten)
    d.text((x3, 150), ".com", font=nos, fill=AMBER_TEXT)
    assert x3 + d.textlength(".com", font=nos) < 1140, "la marca no cabe en la imagen"
    d.text((x + 4, 300), "Comparamos lo que cuentan los medios", font=font("Medium", 42), fill=INK)
    d.text((x + 4, 352), "con lo que dicen los datos.", font=font("Medium", 42), fill=INK)
    d.rectangle((0, 560, 1200, 630), fill=INK)
    d.text(
        (90, 578),
        "Sin bandos. Con datos: INE · Eurostat · Banco Mundial · BOE · GDELT",
        font=font("SemiBold", 28),
        fill=PAPER,
    )
    return img


MARK_SVG = (
    '<rect width="64" height="64" rx="14" fill="{ink}"/>'
    '<rect x="13" y="20" width="38" height="8" rx="4" fill="{paper}"/>'
    '<rect x="13" y="36" width="22" height="8" rx="4" fill="{amber}"/>'
)


def outline(text: str, weight: str, x: float, baseline: float, size: float, fill: str) -> tuple[str, float]:
    """Texto convertido a trazados SVG con la fuente Inter; devuelve (svg, avance en px)."""
    f = TTFont(str(FONTS / f"Inter-{weight}.otf"))
    glyphs, cmap, hmtx = f.getGlyphSet(), f.getBestCmap(), f["hmtx"]
    scale = size / f["head"].unitsPerEm
    parts = []
    for ch in text:
        name = cmap[ord(ch)]
        pen = SVGPathPen(glyphs)
        glyphs[name].draw(pen)
        d = pen.getCommands()
        if d:
            parts.append(
                f'<path transform="translate({x:.2f} {baseline}) scale({scale:.5f} {-scale:.5f})" d="{d}"/>'
            )
        x += hmtx[name][0] * scale
    return f'<g fill="{fill}">{"".join(parts)}</g>', x


def logo_svg() -> str:
    size, baseline = 56, 49
    a, x = outline("nos", "Medium", 80, baseline, size, INK)
    b, x = outline("mienten", "ExtraBold", x, baseline, size, INK)
    c, x = outline(".com", "Medium", x, baseline, size, AMBER_TEXT)
    mark_svg = MARK_SVG.format(ink=INK, paper=PAPER, amber=AMBER)
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {x + 2:.0f} 64" role="img" '
        f'aria-label="nosmienten.com"><title>nosmienten.com</title>{mark_svg}{a}{b}{c}</svg>\n'
    )


def main() -> None:
    (STATIC / "logo.svg").write_text(logo_svg(), encoding="utf-8")
    for size in (180, 192, 512):
        mark(size).save(STATIC / f"icon-{size}.png", optimize=True)
    mark(256).save(STATIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])
    og().save(STATIC / "og-default.png", optimize=True)


if __name__ == "__main__":
    main()
