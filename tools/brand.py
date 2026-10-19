"""Genera los activos de la marca nosmienten.com (ADR 0011; simbolo revisado en el ADR 0014).

Uso: python tools/brand.py  (necesita fontTools, cairosvg, Pillow y la fuente Inter, OFL 1.1; solo en
desarrollo). Escribe en truthnews/web/static/:
- mark.svg: el simbolo, la "n medida" (el arco de la n baja hasta una vara graduada); favicon.svg: la
  misma n sin graduacion, sobre papel, para 16-32 px;
- logo.svg: simbolo + "nos" (Inter Medium) + "mienten" (Inter ExtraBold, con el punto de la i hecho una
  marca cuadrada ambar) + ".com" en ambar oscuro, en contornos para que no dependa de las fuentes;
- favicon.ico (16/32/48), icon-180.png (apple-touch, opaco), icon-192.png, icon-512.png,
  icon-maskable-512.png (zona segura del 80 %) y avatar-400.png (foto de perfil en redes);
- og-default.png (1200x630, imagen por defecto para redes sociales) y banner-1500x500.png (cabecera de
  perfil), con la regla graduada como recurso grafico.
Y anade la i sin punto (U+0131) al subconjunto Inter ExtraBold de truthnews/web/fonts/.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import cairosvg
from fontTools import subset
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.ttLib import TTFont
from PIL import Image

STATIC = Path(__file__).resolve().parents[1] / "truthnews" / "web" / "static"
INK, PAPER, AMBER, AMBER_TEXT = "#14161b", "#fbfaf6", "#e8a317", "#8a5a00"
FONTS = Path("/usr/share/fonts/opentype/inter")
# Graduacion de la vara: (y, largo) en la rejilla de 64; larga-corta-larga-corta-larga, como una regla.
TICKS = ((35.6, 5.2), (39.4, 3), (43.2, 5.2), (47, 3), (50.8, 5.2))
# Punto de la i de Inter ExtraBold sustituido por un cuadrado: (x del tallo, techo del punto, lado), en em.
I_DOT = (115, 1585, 349)
LEMA = ("Comparamos lo que cuentan los medios", "con lo que dicen los datos.")
SOURCES = "INE · Eurostat · Banco Mundial · BOE · GDELT"


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


def outline(
    text: str, weight: str, x: float, baseline: float, size: float, fill: str, mark_i: bool = False
) -> tuple[str, float]:
    """Texto convertido a trazados SVG con la fuente Inter; devuelve (svg, avance en px). Con `mark_i` (solo
    "mienten" del logotipo) la i pierde su punto y gana una marca cuadrada ambar: la medida en el nombre."""
    f = TTFont(str(FONTS / f"Inter-{weight}.otf"))
    glyphs, cmap, hmtx = f.getGlyphSet(), f.getBestCmap(), f["hmtx"]
    scale = size / f["head"].unitsPerEm
    parts, dots = [], []
    for ch in text:
        dotted = mark_i and ch == "i"
        name = cmap[0x131 if dotted else ord(ch)]
        pen = SVGPathPen(glyphs)
        glyphs[name].draw(pen)
        d = pen.getCommands()
        if d:
            parts.append(
                f'<path transform="translate({x:.2f} {baseline}) scale({scale:.5f} {-scale:.5f})" d="{d}"/>'
            )
        if dotted:
            x0, top, side = I_DOT
            dots.append(
                f'<rect x="{x + x0 * scale:.2f}" y="{baseline - top * scale:.2f}" width="{side * scale:.2f}" '
                f'height="{side * scale:.2f}" fill="{AMBER}"/>'
            )
        x += hmtx[name][0] * scale
    return f'<g fill="{fill}">{"".join(parts)}</g>{"".join(dots)}', x


def logo_svg() -> str:
    """El simbolo ocupa x 12-52 de su rejilla; el nombre arranca tras un hueco y apoya en el pie de la n."""
    size, baseline = 56, 54
    a, x = outline("nos", "Medium", 62, baseline, size, INK)
    b, x = outline("mienten", "ExtraBold", x, baseline, size, INK, mark_i=True)
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


def ruler(x0: float, x1: float, y: float, step: float) -> str:
    """Recurso grafico de la marca: una regla con marcas cortas cada `step` y largas cada cinco."""
    marks = [f'<rect x="{x0:g}" y="{y:g}" width="{x1 - x0:g}" height="2" fill="{INK}"/>']
    i = 0
    while (x := x0 + i * step) <= x1 - 1:
        tall = 14 if i % 5 == 0 else 7
        marks.append(f'<rect x="{x:.1f}" y="{y + 2:g}" width="2" height="{tall}" fill="{INK}"/>')
        i += 1
    return "".join(marks)


def logo_inner(x: float, y: float, scale: float) -> str:
    body = logo_svg()
    inner = body[body.index("</title>") + 8 : body.rindex("</svg>")]
    return f'<g transform="translate({x:g} {y:g}) scale({scale:g})">{inner}</g>'


def text(t: str, weight: str, x: float, baseline: float, size: float, fill: str) -> str:
    return outline(t, weight, x, baseline, size, fill)[0]


def centered(t: str, weight: str, cx: float, baseline: float, size: float, fill: str) -> str:
    width = outline(t, weight, 0, baseline, size, fill)[1]
    return text(t, weight, cx - width / 2, baseline, size, fill)


def og() -> str:
    """Imagen social por defecto: logotipo, que hacemos, la regla y la banda de tinta con las fuentes."""
    width = float(logo_svg().split('viewBox="0 0 ')[1].split()[0])
    assert 90 + width * 1.75 < 1110, "la marca no cabe en la imagen"
    return svg(
        f'<rect width="1200" height="630" fill="{PAPER}"/>'
        + logo_inner(90, 100, 1.75)
        + text(LEMA[0], "Medium", 90, 300, 44, INK)
        + text(LEMA[1], "Medium", 90, 356, 44, INK)
        + ruler(90, 1110, 440, 17)
        + f'<rect y="560" width="1200" height="70" fill="{INK}"/>'
        + text(f"Sin bandos. Con datos: {SOURCES}", "SemiBold", 90, 605, 28, PAPER),
        1200,
        630,
    )


def banner() -> str:
    """Cabecera de perfil 1500x500 (X, Bluesky, LinkedIn). Las redes tapan la esquina inferior izquierda con
    la foto: el logotipo va centrado y la regla corre por debajo de lado a lado."""
    width = float(logo_svg().split('viewBox="0 0 ')[1].split()[0]) * 1.5
    x = (1500 - width) / 2
    return svg(
        f'<rect width="1500" height="500" fill="{PAPER}"/>'
        + logo_inner(x, 150, 1.5)
        + centered(f"{LEMA[0]} {LEMA[1]}", "Medium", 750, 300, 30, INK)
        + ruler(0, 1500, 380, 20),
        1500,
        500,
    )


def dotless_subset() -> None:
    """La imagen por historia dibuja "mienten" con la i sin punto: el subconjunto necesita U+0131."""
    fonts = STATIC.parent / "fonts"
    path = fonts / "Inter-ExtraBold.otf"
    chars = set(TTFont(str(path)).getBestCmap()) | {0x131}
    sub = subset.Subsetter(subset.Options())
    font = TTFont(str(FONTS / "Inter-ExtraBold.otf"))
    sub.populate(unicodes=sorted(chars))
    sub.subset(font)
    font.save(str(path))


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
    raster(og(), 1200, 630).save(STATIC / "og-default.png", optimize=True)
    raster(banner(), 1500, 500).save(STATIC / "banner-1500x500.png", optimize=True)
    dotless_subset()


if __name__ == "__main__":
    main()
