"""Graficos SVG del servidor, sin JS ni librerias (ADR 0050).

Dos formas, pensadas para movil (viewBox de 360 de ancho, texto de 11-12 unidades):

- **Lo que dijo y cuando** (ficha de entidad): un carril por veredicto con su nombre escrito, cada afirmacion
  un punto en su fecha, coloreado por su veredicto y con forma propia (el color no es la unica pista: verde y
  ambar no se distinguen con protanopia, medido con el validador de paleta). Cada punto enlaza a su
  verificacion o a su noticia y lleva su `<title>` (detalle al pasar el raton, sin JS).
- **La cifra en el tiempo** (historia): el valor que da cada medio en su hora, frente a la linea discontinua
  del dato oficial cuando lo hay; los cambios de una misma noticia se dibujan como anillo con flecha.

Todo grafico lleva `role="img"`-equivalente accesible: `<title>` y `<desc>` con los numeros, y la pagina
conserva la lista o tabla con el mismo contenido.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from html import escape

from markupsafe import Markup

W = 360  # ancho del viewBox: en un movil de 390 px el texto de 11 unidades se lee a ~12 px
PAD_L, PAD_R = 8, 12
VERDICT_COLOR = {
    "verdadero": "#1b7a3a",
    "impreciso": "#b07300",
    "falso": "#b3001b",
    "enganoso": "#7a2a8c",
    "sin-datos": "#6b6b6b",
}
# Carriles de arriba abajo: lo que no cuadra primero.
LANES = (
    ("falso", ("falso", "enganoso")),
    ("impreciso", ("impreciso",)),
    ("verdadero", ("verdadero",)),
    ("sin-datos", ("sin-datos", None)),
)
LANE_KEYS = tuple(k for k, _ in LANES)
INK, MUTED, GRID = "#14161b", "#595959", "#e3e0d8"


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _fmt(v: float, unit: str = "") -> str:
    if unit == "pct":
        return f"{v:.1f}".replace(".", ",") + " %"
    if abs(v - round(v)) < 1e-9:
        return f"{round(v):,}".replace(",", ".")
    return f"{v:,.1f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _time_scale(times: list[datetime], x0: float, x1: float):
    lo, hi = min(times), max(times)
    span = (hi - lo).total_seconds()
    if span <= 0:
        return lambda t: (x0 + x1) / 2, lo, hi
    return lambda t: x0 + (x1 - x0) * (_aware(t) - lo).total_seconds() / span, lo, hi


def _date_label(t: datetime, span_days: float) -> str:
    return f"{t:%d/%m %H:%M}" if span_days < 2 else f"{t:%d/%m/%y}"


def _marker(kind: str, x: float, y: float, color: str, r: float = 5) -> str:
    """Forma por veredicto: circulo (verdadero), triangulo (impreciso), cuadrado (falso/enganoso), anillo."""
    ring = 'stroke="#fbfaf6" stroke-width="2"'  # anillo del color del papel: separa puntos solapados
    if kind == "verdadero":
        return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}" {ring}/>'
    if kind == "impreciso":
        h = r * 1.15
        pts = f"{x:.1f},{y - h:.1f} {x + h:.1f},{y + h * 0.8:.1f} {x - h:.1f},{y + h * 0.8:.1f}"
        return f'<polygon points="{pts}" fill="{color}" {ring}/>'
    if kind in ("falso", "enganoso"):
        s = r * 1.7
        return (
            f'<rect x="{x - s / 2:.1f}" y="{y - s / 2:.1f}" width="{s:.1f}" height="{s:.1f}" '
            f'fill="{color}" {ring}/>'
        )
    return f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r - 1}" fill="#fbfaf6" stroke="{color}" stroke-width="2"/>'


@dataclass
class Said:
    when: datetime
    verdict: str | None  # None = dicho sin afirmacion comprobada
    text: str
    href: str


def said_timeline(points: list[Said], labels: dict[str, str], title: str) -> Markup:
    """Lo que dijo y cuando: un carril por veredicto. `labels` traduce los veredictos (y 'sin-datos')."""
    if not points:
        return Markup("")
    lane_h, top, axis_h, label_w = 26, 6, 20, 104
    lanes = [(key, members) for key, members in LANES if any(p.verdict in members for p in points)]
    h = top + lane_h * len(lanes) + axis_h
    x0, x1 = PAD_L + label_w, W - PAD_R
    xs, lo, hi = _time_scale([_aware(p.when) for p in points], x0 + 6, x1 - 6)
    span = (hi - lo).total_seconds() / 86400
    out = []
    counts = []
    for i, (key, members) in enumerate(lanes):
        y = top + lane_h * i + lane_h / 2
        mine = [p for p in points if p.verdict in members]
        counts.append(f"{labels.get(key, key)}: {len(mine)}")
        out.append(f'<line x1="{x0}" y1="{y:.1f}" x2="{x1}" y2="{y:.1f}" stroke="{GRID}" stroke-width="1"/>')
        out.append(
            f'<text x="{PAD_L}" y="{y + 4:.1f}" font-size="11" fill="{INK}">{escape(labels.get(key, key))}'
            f' <tspan fill="{MUTED}">{len(mine)}</tspan></text>'
        )
        for p in sorted(mine, key=lambda p: p.when):
            kind = p.verdict or "sin-datos"
            color = VERDICT_COLOR.get(kind, VERDICT_COLOR["sin-datos"])
            tip = f"{_aware(p.when):%d/%m/%Y} · {labels.get(kind, kind)}: {p.text[:160]}"
            out.append(
                f'<a href="{escape(p.href)}"><title>{escape(tip)}</title>'
                f'<rect x="{xs(p.when) - 9:.1f}" y="{y - 11:.1f}" width="18" height="22" fill="transparent"/>'
                f"{_marker(kind, xs(p.when), y, color)}</a>"
            )
    ya = top + lane_h * len(lanes) + 14
    out.append(f'<text x="{x0}" y="{ya}" font-size="10" fill="{MUTED}">{_date_label(lo, span)}</text>')
    if span > 0:
        out.append(
            f'<text x="{x1}" y="{ya}" font-size="10" fill="{MUTED}" text-anchor="end">'
            f"{_date_label(hi, span)}</text>"
        )
    desc = f"{len(points)} afirmaciones entre {lo:%d/%m/%Y} y {hi:%d/%m/%Y}. " + "; ".join(counts) + "."
    return Markup(
        f'<svg class="chart said" viewBox="0 0 {W} {h}" role="img" aria-labelledby="st-t st-d" '
        f'xmlns="http://www.w3.org/2000/svg"><title id="st-t">{escape(title)}</title>'
        f'<desc id="st-d">{escape(desc)}</desc>{"".join(out)}</svg>'
    )


@dataclass
class Point:
    who: str
    when: datetime
    value: float
    href: str = ""
    before: float | None = None  # si la noticia cambio la cifra: el valor anterior


def figure_chart(
    points: list[Point],
    title: str,
    unit: str = "",
    official: float | None = None,
    official_label: str = "",
    chart_id: str = "fc",
) -> Markup:
    """La cifra en el tiempo: cada medio en su hora; linea discontinua del dato oficial si lo hay."""
    if not points:
        return Markup("")
    h, top, bottom, left = 150, 14, 22, 44
    x0, x1 = left, W - PAD_R
    xs, lo, hi = _time_scale([_aware(p.when) for p in points], x0 + 8, x1 - 8)
    vals = [p.value for p in points] + [p.before for p in points if p.before is not None]
    if official is not None:
        vals.append(official)
    vmin, vmax = min(vals), max(vals)
    if vmin == vmax:
        vmin, vmax = vmin * 0.9, (vmax * 1.1) or 1
    pad = (vmax - vmin) * 0.12
    vmin, vmax = max(0.0, vmin - pad) if vmin >= 0 else vmin - pad, vmax + pad

    def ys(v: float) -> float:
        return top + (h - top - bottom) * (1 - (v - vmin) / (vmax - vmin))

    out = [
        f'<line x1="{x0}" y1="{h - bottom}" x2="{x1}" y2="{h - bottom}" stroke="{GRID}"/>',
        f'<text x="{x0 - 4}" y="{ys(vmax) + 4:.1f}" font-size="10" fill="{MUTED}" text-anchor="end">'
        f"{_fmt(vmax, unit)}</text>",
        f'<text x="{x0 - 4}" y="{ys(vmin) + 4:.1f}" font-size="10" fill="{MUTED}" text-anchor="end">'
        f"{_fmt(vmin, unit)}</text>",
    ]
    if official is not None:
        yo = ys(official)
        out.append(
            f'<line x1="{x0}" y1="{yo:.1f}" x2="{x1}" y2="{yo:.1f}" stroke="{VERDICT_COLOR["verdadero"]}" '
            f'stroke-width="2" stroke-dasharray="5 4"/>'
            f'<text x="{x1}" y="{yo - 5:.1f}" font-size="11" fill="{INK}" text-anchor="end">'
            f"{escape(official_label)} {_fmt(official, unit)}</text>"
        )
    span = (hi - lo).total_seconds() / 86400
    ext = {min(points, key=lambda p: p.value).value, max(points, key=lambda p: p.value).value}
    labelled: set[float] = set()
    for p in sorted(points, key=lambda p: p.when):
        x, y = xs(p.when), ys(p.value)
        tip = f"{p.who} · {_aware(p.when):%d/%m %H:%M} · {_fmt(p.value, unit)}"
        mark = f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{INK}" stroke="#fbfaf6" stroke-width="2"/>'
        if p.before is not None:
            yb = ys(p.before)
            tip += f" (antes {_fmt(p.before, unit)})"
            mark = (
                f'<line x1="{x:.1f}" y1="{yb:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
                f'stroke="{MUTED}" stroke-width="2"/>'
                f'<circle cx="{x:.1f}" cy="{yb:.1f}" r="4" fill="#fbfaf6" '
                f'stroke="{MUTED}" stroke-width="2"/>{mark}'
            )
        body = f"<title>{escape(tip)}</title>{mark}"
        out.append(f'<a href="{escape(p.href)}">{body}</a>' if p.href else f"<g>{body}</g>")
        if p.value in ext and p.value not in labelled:  # etiquetas solo en los extremos, sin pisar
            labelled.add(p.value)
            anchor = "end" if x > (x0 + x1) / 2 else "start"
            dx = -8 if anchor == "end" else 8
            out.append(
                f'<text x="{x + dx:.1f}" y="{y + 4:.1f}" font-size="11" fill="{INK}" text-anchor="{anchor}">'
                f"{_fmt(p.value, unit)} · {escape(p.who[:18])}</text>"
            )
    out.append(f'<text x="{x0}" y="{h - 6}" font-size="10" fill="{MUTED}">{_date_label(lo, span)}</text>')
    if span > 0:
        out.append(
            f'<text x="{x1}" y="{h - 6}" font-size="10" fill="{MUTED}" text-anchor="end">'
            f"{_date_label(hi, span)}</text>"
        )
    parts = [f"{p.who} {_fmt(p.value, unit)} ({_aware(p.when):%d/%m %H:%M})" for p in points]
    desc = "; ".join(parts) + (f". {official_label} {_fmt(official, unit)}." if official is not None else ".")
    return Markup(
        f'<svg class="chart fig" viewBox="0 0 {W} {h}" role="img" '
        f'aria-labelledby="{chart_id}-t {chart_id}-d" '
        f'xmlns="http://www.w3.org/2000/svg"><title id="{chart_id}-t">{escape(title)}</title>'
        f'<desc id="{chart_id}-d">{escape(desc)}</desc>{"".join(out)}</svg>'
    )


def said_points(claims: list, quotes: list) -> list[Said]:
    """Puntos de 'lo que dijo y cuando': afirmaciones comprobadas (con veredicto) y frases sin comprobar."""
    pts = [
        Said(c.article.published_at, c.verification.verdict, c.text, f"/verificacion/{c.id}")
        for c in claims
        if c.verification is not None and c.article is not None
    ]
    said = {c.text for c in claims}
    pts += [
        Said(q.published_at, None, q.quote, f"/noticia/{q.article_id}") for q in quotes if q.quote not in said
    ]
    return pts


def story_figure_charts(
    arts: list, comp, claims: list, labels: dict[str, str], limit: int = 3, revisions: list | None = None
) -> list[Markup]:
    """La cifra en el tiempo: datos oficiales primero, despues cifras en disputa o cambiadas."""
    from truthnews.analysis.claims import indicator_name
    from truthnews.analysis.compare import figures
    from truthnews.web import seo

    charts: list[Markup] = []
    # 1) Afirmaciones con dato oficial: cada medio frente a la linea del dato.
    by_ind: dict[tuple, list] = {}
    for c in claims:
        ev = next(
            (e for e in (c.verification.evidence if c.verification else []) if e.value is not None), None
        )
        if ev is not None and c.article is not None:
            by_ind.setdefault((c.indicator, c.geo, ev.value, ev.source, ev.period, c.unit), []).append(c)
    for i, ((ind, geo, official, source, period, unit), cs) in enumerate(by_ind.items()):
        pts = [Point(c.outlet.name, c.article.published_at, c.value, f"/verificacion/{c.id}") for c in cs]
        label = f"{labels['official']} ({source}{', ' + period if period else ''})"
        title = f"{indicator_name(ind)} ({geo})"
        charts.append(figure_chart(pts, title, unit, official, label, chart_id=f"fo{i}"))
    # 2) Cifras en disputa del mismo hecho y cifras que una noticia cambio despues de publicarse.
    by_outlet = {a.outlet.name: a for a in arts}
    changed: dict[str, list[Point]] = {}
    by_id = {a.id: a for a in arts}
    # Las revisiones llegan en una sola consulta (la ruta); sin ellas no se recorre a.revisions (N+1).
    for r in revisions or []:
        a = by_id.get(r.article_id)
        if a is not None:
            old = {n: v for n, v, *_ in figures(r.before)}
            for noun, value, *_ in figures(r.after):
                if noun in old and old[noun] != value:
                    href = seo.path("noticia", a.id, a.title)
                    changed.setdefault(noun, []).append(
                        Point(a.outlet.name, r.detected_at, value, href, old[noun])
                    )
    for i, figs in enumerate(comp.disputes.values()):
        noun = figs[0].noun
        pts = []
        for f in figs:
            a = by_outlet.get(f.outlet)
            pts.append(
                Point(f.outlet, f.published_at, f.value, seo.path("noticia", a.id, a.title) if a else "")
            )
        pts += changed.pop(noun, [])
        charts.append(figure_chart(pts, f"{noun.capitalize()} · {labels['by_outlet']}", chart_id=f"fd{i}"))
    for i, (noun, pts) in enumerate(changed.items()):
        charts.append(figure_chart(pts, f"{noun.capitalize()} · {labels['changed']}", chart_id=f"fc{i}"))
    return charts[:limit]
