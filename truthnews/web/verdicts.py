"""Veredicto mascado: una frase y un grafico de la serie oficial con la cifra del medio marcada.

El grafico es SVG pintado en el servidor (sin scripts de terceros) y lleva su tabla de datos al lado.
La serie oficial va en tinta (referencia neutra) y la cifra del medio en ambar con su propia forma
(linea discontinua y rombo) y etiqueta directa: la identidad nunca depende solo del color.
"""

from __future__ import annotations

import re

from markupsafe import Markup, escape

from truthnews.analysis.claims import indicator_name
from truthnews.registry import t

W, H = 480, 260
PAD_L, PAD_R, PAD_T, PAD_B = 50, 112, 18, 34
SOURCE_NAMES = {
    "ine": "INE",
    "eurostat": "Eurostat",
    "worldbank": {"es": "Banco Mundial", "en": "World Bank"},
    "ecb": {"es": "BCE", "en": "ECB"},
}
INK, CLAIM, GRID = "#14161b", "#8a5a00", "#e3e0d8"


_RETIRED = re.compile(r"\[Retirado el (\d{2}/\d{2}/\d{4}): (.*?)\]")


def retired_note(v) -> tuple[str, str] | None:
    """(fecha, motivo) si la redaccion retiro el veredicto a mano y sigue retirado (ADR 0049)."""
    if v is None or not (v.method or "").startswith("retirada-manual"):
        return None
    found = _RETIRED.findall(v.explanation or "")
    return found[-1] if found else None


def dato(value: float | None, unit: str | None = None, lang: str = "es") -> str:
    """Un dato oficial legible: 10,0 % o 1.234,5 (es); 10.0% o 1,234.5 (en)."""
    if value is None:
        return "—"
    if unit == "pct":
        return f"{value:.1f}%" if lang == "en" else f"{value:.1f}".replace(".", ",") + " %"
    text = f"{value:,.1f}" if value % 1 else f"{value:,.0f}"
    return text if lang == "en" else text.replace(",", "_").replace(".", ",").replace("_", ".")


def _gap(claim, official: float, lang: str) -> str:
    sep = "." if lang == "en" else ","
    if claim.unit == "pct":
        return f"{abs(claim.value - official):.1f}".replace(".", sep) + " " + t(lang, "points_unit")
    rel = abs(claim.value - official) / max(abs(official), 1e-9) * 100
    return dato(rel, "pct", lang)


def sentence(claim, lang: str = "es") -> str:
    """El veredicto en una frase, con quien lo dice, lo que dice y lo que dice el dato oficial."""
    v = claim.verification
    name = indicator_name(claim.indicator, lang)
    who = claim.outlet.name
    ev = [e for e in v.evidence if e.value is not None]
    if v.verdict == "sin-datos" or not ev:
        return t(lang, "vs_sin-datos").format(who=who, said=dato(claim.value, claim.unit, lang), ind=name)
    off = ev[0]
    ctx = {
        "who": who,
        "said": dato(claim.value, claim.unit, lang),
        "ind": name,
        "official": dato(off.value, claim.unit, lang),
        "period": off.period or "",
        "source": source_name(off.source, lang),
        "gap": _gap(claim, off.value, lang),
    }
    if v.verdict == "enganoso" and len(ev) > 1:
        ctx["real"] = t(lang, "trend_up" if ev[0].value > ev[1].value else "trend_down")
        ctx["claimed"] = t(lang, "trend_up" if claim.direction == "sube" else "trend_down")
        ctx["prev_period"] = ev[1].period or ""
    return t(lang, f"vs_{v.verdict}").format(**ctx)


def source_name(source: str, lang: str = "es") -> str:
    name = SOURCE_NAMES.get(source, source)
    return name.get(lang, name["es"]) if isinstance(name, dict) else name


def series_of(claim) -> list[tuple[str, float]]:
    """Serie oficial guardada con la evidencia (ultimos periodos), o solo los puntos de la evidencia."""
    ev = [e for e in claim.verification.evidence if e.value is not None]
    if not ev:
        return []
    serie = (ev[0].payload or {}).get("serie") or {}
    points = {str(k): float(v) for k, v in serie.items()}
    for e in ev:
        points.setdefault(e.period or "", e.value)
    return sorted((k, v) for k, v in points.items() if k)


def chart(claim, lang: str = "es") -> Markup:
    """SVG accesible: serie oficial (linea y puntos con su valor al pasar) y la cifra del medio."""
    pts = series_of(claim)
    if not pts:
        return Markup("")
    ev = [e for e in claim.verification.evidence if e.value is not None]
    cited = ev[0].period if ev else pts[-1][0]
    values = [v for _, v in pts] + [claim.value]
    lo, hi = min(values), max(values)
    if hi - lo < 1e-9:
        lo, hi = lo - 1, hi + 1
    span = hi - lo
    lo, hi = lo - span * 0.12, hi + span * 0.12
    iw, ih = W - PAD_L - PAD_R, H - PAD_T - PAD_B

    def x(i: int) -> float:
        return PAD_L + (iw * i / (len(pts) - 1) if len(pts) > 1 else iw / 2)

    def y(v: float) -> float:
        return PAD_T + ih * (1 - (v - lo) / (hi - lo))

    unit = claim.unit
    name = indicator_name(claim.indicator, lang)
    title = t(lang, "chart_title").format(ind=name, who=claim.outlet.name)
    out = [
        f'<svg class="vchart" viewBox="0 0 {W} {H}" role="img" aria-labelledby="vc-t" '
        f'preserveAspectRatio="xMidYMid meet"><title id="vc-t">{escape(title)}</title>'
    ]
    for v in (lo + (hi - lo) * f for f in (0.12 / 1.24, 0.5, 1 - 0.12 / 1.24)):
        out.append(_hline(y(v), GRID, 1) + _text(PAD_L - 6, y(v) + 4, "vc-ax", dato(v, unit, lang), "end"))
    if len(pts) > 1:
        path = " ".join(f"{'M' if i == 0 else 'L'}{x(i):.1f},{y(v):.1f}" for i, (_, v) in enumerate(pts))
        out.append(f'<path d="{path}" fill="none" stroke="{INK}" stroke-width="2" stroke-linejoin="round"/>')
    ci = next((i for i, (p, _) in enumerate(pts) if p == cited), len(pts) - 1)
    for i, (p, v) in enumerate(pts):
        r = 5 if i == ci else 3.5
        out.append(
            f'<circle cx="{x(i):.1f}" cy="{y(v):.1f}" r="{r}" fill="{INK}" stroke="#fbfaf6" stroke-width="2">'
            f"<title>{escape(p)}: {escape(dato(v, unit, lang))}</title></circle>"
        )
    for i in sorted({0, len(pts) - 1}):
        anchor = "start" if i == 0 and len(pts) > 1 else "end" if len(pts) > 1 else "middle"
        out.append(_text(x(i), H - 8, "vc-ax", pts[i][0], anchor))
    yc, yo = y(claim.value), y(pts[ci][1])
    said = dato(claim.value, unit, lang)
    out.append(
        _hline(yc, CLAIM, 2, ' stroke-dasharray="6 4"')
        + f'<path d="M{x(ci):.1f},{yc - 7:.1f} l7,7 l-7,7 l-7,-7 z" fill="{CLAIM}" stroke="#fbfaf6" '
        f'stroke-width="2"><title>{escape(claim.outlet.name)}: {escape(said)}</title>'
        "</path>"
    )
    # Etiquetas directas a la derecha; si se pisan, se separan en vertical.
    lc, lo_ = yc + 4, yo + 4
    if abs(lc - lo_) < 38:
        lc, lo_ = (lc - 19, lo_ + 19) if yc <= yo else (lc + 19, lo_ - 19)
    lx = W - PAD_R + 8
    out.append(
        _text(lx, lc, "vc-lab vc-claim", said)
        + _text(lx, lc + 16, "vc-ax", _short(claim.outlet.name))
        + _text(lx, lo_, "vc-lab", dato(pts[ci][1], unit, lang))
        + _text(lx, lo_ + 16, "vc-ax", f"{t(lang, 'official_short')} {pts[ci][0]}")
    )
    out.append("</svg>")
    return Markup("".join(out))


def _text(x: float, y: float, cls: str, text: str, anchor: str = "start") -> str:
    return f'<text x="{x:.1f}" y="{y:.1f}" text-anchor="{anchor}" class="{cls}">{escape(text)}</text>'


def _hline(y: float, color: str, width: int, extra: str = "") -> str:
    return (
        f'<line x1="{PAD_L}" x2="{W - PAD_R}" y1="{y:.1f}" y2="{y:.1f}" stroke="{color}" '
        f'stroke-width="{width}"{extra}/>'
    )


def _short(name: str, n: int = 13) -> str:
    return name if len(name) <= n else name[: n - 1] + "…"
