"""La historia en claro: en que coinciden los medios, en que difieren y que dicen los datos.

Frases cortas calculadas con el mismo metodo para todos los medios (sin calificativos): la conclusion
primero y el detalle despues, en la pagina. Nada se afirma que no salga de la comparacion o de una
verificacion con su fuente.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from truthnews.analysis.compare import Comparison

RIGHT = {"verdadero"}
WRONG = {"impreciso", "falso", "enganoso"}


def fmt(value: float | None, unit: str = "") -> str:
    """10,0 % o 1.234,5: un dato legible en espanol."""
    if value is None:
        return "—"
    if unit == "pct":
        return f"{value:.1f}".replace(".", ",") + " %"
    text = f"{value:,.1f}" if value % 1 else f"{value:,.0f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


@dataclass
class Truth:
    """Lo que dice el dato oficial de un indicador y cuantos medios lo cuentan bien."""

    label: str
    official: float | None
    unit: str
    period: str | None
    source: str
    url: str
    right: list[str] = field(default_factory=list)
    wrong: list[tuple[str, str, str]] = field(default_factory=list)  # (medio, valor dicho, veredicto)

    @property
    def official_text(self) -> str:
        return fmt(self.official, self.unit)


@dataclass
class Plain:
    truths: list[Truth]
    differ: list[dict]  # sustantivo, rango, cifra mas repetida y la ultima publicada
    agree: list[tuple[str, int, int]]  # (sustantivo, valor, medios)
    blame_differs: bool
    n_outlets: int

    @property
    def empty(self) -> bool:
        return not (self.truths or self.differ or self.agree or self.blame_differs)


def truths_of(claims: list) -> list[Truth]:
    """Agrupa las verificaciones con dato por indicador y territorio."""
    out: dict[tuple[str, str], Truth] = {}
    for c in claims:
        v = c.verification
        if v is None or v.verdict not in RIGHT | WRONG or not v.evidence:
            continue
        e = v.evidence[0]
        t = out.get((c.indicator, c.geo))
        if t is None:
            t = out[(c.indicator, c.geo)] = Truth(e.label, e.value, c.unit, e.period, e.source, e.url)
        name = c.outlet.name
        if v.verdict in RIGHT:
            if name not in t.right:
                t.right.append(name)
        elif all(name != w[0] for w in t.wrong):
            t.wrong.append((name, fmt(c.value, c.unit), v.verdict))
    return list(out.values())


def in_plain_words(comp: Comparison, claims: list) -> Plain:
    differ = []
    for d in comp.dispute_summaries():
        latest = max((f for _, figs in d.groups for f in figs), key=lambda f: f.published_at)
        differ.append(
            {
                "noun": d.noun,
                "low": d.low,
                "high": d.high,
                "mode": d.mode if d.mode_n >= 2 else None,
                "mode_n": d.mode_n,
                "latest": latest,
            }
        )
    return Plain(truths_of(claims), differ, comp.agreed_figures, comp.blame_differs, len(comp.outlets))
