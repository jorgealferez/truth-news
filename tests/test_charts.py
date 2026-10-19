from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from truthnews.analysis.compare import compare
from truthnews.web import charts

T0 = datetime(2026, 10, 19, 8, tzinfo=UTC)
LANES = {
    "falso": "Falso o enganoso",
    "impreciso": "Impreciso",
    "verdadero": "Verdadero",
    "sin-datos": "Sin comprobar",
}
LABELS = {"official": "Dato oficial", "by_outlet": "cifra de cada medio", "changed": "cifra cambiada"}


def test_said_timeline_lanes_shapes_links_and_description():
    pts = [
        charts.Said(T0, "falso", "El paro esta en el 14,5 %", "/verificacion/1"),
        charts.Said(T0 + timedelta(days=3), "verdadero", "El IPC subio al 3 %", "/verificacion/2"),
        charts.Said(T0 + timedelta(days=5), None, "Vamos a <ganar>", "/noticia/9"),
    ]
    svg = str(charts.said_timeline(pts, LANES, "Lo que dijo y cuando"))
    assert svg.startswith('<svg class="chart said"') and 'role="img"' in svg
    assert (
        "<rect" in svg and "<circle" in svg
    )  # cuadrado (falso), circulo (verdadero), anillo (sin comprobar)
    assert 'href="/verificacion/1"' in svg and 'href="/noticia/9"' in svg
    assert "Falso o enganoso" in svg and "Impreciso" not in svg  # solo carriles con puntos
    assert "3 afirmaciones entre 19/10/2026 y 24/10/2026" in svg and "Falso o enganoso: 1" in svg
    assert "&lt;ganar&gt;" in svg and "<ganar>" not in svg  # el texto se escapa
    assert str(charts.said_timeline([], LANES, "x")) == ""


def test_figure_chart_official_line_extremes_and_changes():
    pts = [
        charts.Point("Medio A", T0, 1200, "/noticia/1"),
        charts.Point("Medio B", T0 + timedelta(hours=2), 2400, "/noticia/2"),
        charts.Point("Medio C", T0 + timedelta(hours=3), 2000, "", before=1800),
    ]
    svg = str(
        charts.figure_chart(pts, "Detenidos", official=1500, official_label="Dato oficial", chart_id="t")
    )
    assert 'stroke-dasharray="5 4"' in svg and "Dato oficial 1.500" in svg
    assert "1.200 · Medio A" in svg and "2.400 · Medio B" in svg and "2.000 · Medio C" not in svg  # extremos
    assert "(antes 1.800)" in svg and 'aria-labelledby="t-t t-d"' in svg
    assert "Medio A 1.200 (19/10 08:00); Medio B 2.400" in svg
    pct = str(charts.figure_chart([charts.Point("X", T0, 10.5)], "Paro", unit="pct"))
    assert "10,5 %" in pct and "<g><title>" in pct  # sin enlace: grupo, no <a>
    assert str(charts.figure_chart([], "x")) == ""


def test_story_figure_charts_from_claims_disputes_and_revisions():
    outs = [NS(name=f"M{i}", slug=f"m{i}") for i in range(3)]
    arts = [
        NS(
            id=1,
            title="El incendio deja 3 muertos",
            summary="",
            outlet=outs[0],
            published_at=T0,
            revisions=[],
        ),
        NS(
            id=2,
            title="El incendio deja 5 muertos",
            summary="",
            outlet=outs[1],
            published_at=T0 + timedelta(hours=1),
            revisions=[
                NS(before="Hay 2 heridos", after="Hay 4 heridos", detected_at=T0 + timedelta(hours=2))
            ],
        ),
    ]
    comp = compare(
        [NS(**{**vars(a), "language": "es", "category": "sucesos", "content_text": None}) for a in arts]
    )
    ev = NS(value=10.5, source="ine", period="2026-Q3")
    claims = [
        NS(
            id=7,
            indicator="paro",
            geo="ES",
            unit="pct",
            value=14.5,
            outlet=outs[2],
            article=NS(published_at=T0),
            verification=NS(evidence=[ev]),
        )
    ]
    revs = [
        NS(article_id=2, before="Hay 2 heridos", after="Hay 4 heridos", detected_at=T0 + timedelta(hours=2))
    ]
    out = [str(c) for c in charts.story_figure_charts(arts, comp, claims, LABELS, revisions=revs)]
    assert len(out) == 3
    assert "Tasa de paro (ES)" in out[0] and "Dato oficial (ine, 2026-Q3) 10,5 %" in out[0]
    assert "Muertos · cifra de cada medio" in out[1] and "5 · M1" in out[1]
    assert "Heridos · cifra cambiada" in out[2] and "(antes 2)" in out[2]
    assert len(charts.story_figure_charts(arts, comp, claims, LABELS, limit=1)) == 1


def test_said_points_mix_checked_claims_and_quotes():
    claim = NS(id=3, text="Dijo X", article=NS(published_at=T0), verification=NS(verdict="impreciso"))
    unchecked = NS(id=4, text="Sin veredicto", article=NS(published_at=T0), verification=None)
    quotes = [
        NS(published_at=T0, quote="Dijo X", article_id=1),
        NS(published_at=T0, quote="Otra", article_id=2),
    ]
    pts = charts.said_points([claim, unchecked], quotes)
    assert [(p.verdict, p.href) for p in pts] == [("impreciso", "/verificacion/3"), (None, "/noticia/2")]
