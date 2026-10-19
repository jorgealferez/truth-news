"""Genera los activos de la marca nosmienten.com (ADR 0011; simbolo revisado en el ADR 0014).

Uso: python tools/brand.py  (necesita fontTools, cairosvg, Pillow y la fuente Inter, OFL 1.1; solo en
desarrollo). Escribe en truthnews/web/static/:
- mark.svg: el simbolo, la "n medida" (el arco de la n baja hasta una vara graduada); favicon.svg: la
  misma n sin graduacion, sobre papel, para 16-32 px;
- logo.svg: simbolo + "nos" (Inter Medium) + "mienten" (Inter ExtraBold) + ".com" en ambar oscuro, en
  contornos para que no dependa de las fuentes del lector;
- favicon.ico (16/32/48), icon-180.png (apple-touch, opaco), icon-192.png, icon-512.png,
  icon-maskable-512.png (zona segura del 80 %) y avatar-400.png (foto de perfil en redes);
- og-default.png (1200x630, imagen por defecto para redes sociales).
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import cairosvg
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from PIL import Image, ImageDraw, ImageFont

STATIC = Path(__file__).resolve().parents[1] / "truthnews" / "web" / "static"
INK, PAPER, AMBER, AMBER_TEXT = "#14161b", "#fbfaf6", "#e8a317", "#8a5a00"
FONTS = Path("/usr/share/fonts/opentype/inter")
# Graduacion de la vara: (y, largo) en la rejilla de 64; larga-corta-larga-corta-larga, como una regla.
TICKS = ((35.6, 5.2), (39.4, 3), (43.2, 5.2), (47, 3), (50.8, 5.2))


def glyph(ink: str = INK, amber: str = AMBER, cut: str = PAPER, ticks: bool = True) -> str:
    """La "n medida" en una rejilla de 64 (caja 12-52 x 10-54). El arco de la n (lo que se cuenta) baja
    hasta una vara ambar graduada (lo que se mide): el relato llega al dato. La vara va separada del arco,
    es un instrumento apoyado en la letra, y su graduacion se recorta con el color del fondo (`cut`)."""
    out = (
        f'<path d="M12 54V30A20 20 0 0 1 52 30H42A10 10 0 0 0 22 30V54Z" fill="{ink}"/>'
        f'<rect x="42" y="32.4" width="10" height="21.6" fill="{amber}"/>'
    )
    if ticks:
        out += "".join(f'<rect x="42" y="{y}" width="{w}" height="1.5" fill="{cut}"/>' for y, w in TICKS)
    return out


def svg(body: str, w: float, h: float, label: str | None = None) -> str:
    a11y = f' role="img" aria-label="{label}"><title>{label}</title>' if label else ">"
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:g} {h:g}"{a11y}{body}</svg>\n'


def font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / f"Inter-{weight}.otf"), size)


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
    """El simbolo ocupa x 12-52 de su rejilla; el nombre arranca tras un hueco y apoya en el pie de la n."""
    size, baseline = 56, 54
    a, x = outline("nos", "Medium", 62, baseline, size, INK)
    b, x = outline("mienten", "ExtraBold", x, baseline, size, INK)
    c, x = outline(".com", "Medium", x, baseline, size, AMBER_TEXT)
    return svg(f'<g transform="translate(-12 0)">{glyph()}</g>{a}{b}{c}', round(x + 2), 64, "nosmienten.com")


def icon(pad: float, rounded: bool, ticks: bool = True) -> str:
    """Simbolo sobre papel, centrado, con margen `pad` (fraccion del lado)."""
    bg = f'<rect width="64" height="64"{" rx=\"14\"" if rounded else ""} fill="{PAPER}"/>'
    s = 64 * (1 - 2 * pad) / 44  # la caja del simbolo mide 40 x 44
    body = f'<g transform="translate(32 32) scale({s:.4f}) translate(-32 -32)">{glyph(ticks=ticks)}</g>'
    return svg(bg + body, 64, 64)


def raster(source: str, w: int, h: int | None = None) -> Image.Image:
    raw = cairosvg.svg2png(bytestring=source.encode(), output_width=w, output_height=h or w)
    return Image.open(BytesIO(raw))


def og() -> Image.Image:
    img = Image.new("RGB", (1200, 630), PAPER)
    d = ImageDraw.Draw(img)
    sym = raster(svg(glyph(), 64, 64), 200)
    img.paste(sym, (52, 118), sym)
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


def main() -> None:
    (STATIC / "mark.svg").write_text(svg(glyph(), 64, 64, "nosmienten.com"), encoding="utf-8")
    small = icon(0.05, rounded=True, ticks=False)
    (STATIC / "favicon.svg").write_text(small, encoding="utf-8")
    (STATIC / "logo.svg").write_text(logo_svg(), encoding="utf-8")
    raster(icon(0.16, rounded=False), 180).save(STATIC / "icon-180.png", optimize=True)
    for size in (192, 512):
        raster(icon(0.14, rounded=True), size).save(STATIC / f"icon-{size}.png", optimize=True)
    raster(icon(0.22, rounded=False), 512).save(STATIC / "icon-maskable-512.png", optimize=True)
    raster(icon(0.24, rounded=False), 400).save(STATIC / "avatar-400.png", optimize=True)
    frames = [raster(small, s) for s in (16, 32, 48)]
    frames[-1].save(STATIC / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)], append_images=frames[:-1])
    og().save(STATIC / "og-default.png", optimize=True)


if __name__ == "__main__":
    main()
