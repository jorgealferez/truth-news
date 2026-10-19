from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

from truthnews.analysis.compare import compare
from truthnews.analysis.plain import fmt, in_plain_words, truths_of

T0 = datetime(2026, 10, 18, 8, tzinfo=UTC)


def art(outlet, title, minutes=0):
    return NS(
        outlet=NS(name=outlet),
        title=title,
        summary="",
        content_text=None,
        published_at=T0 + timedelta(minutes=minutes),
        language="es",
    )


def claim(outlet, value, verdict, geo="ES"):
    ev = NS(
        label="Tasa de paro", value=10.0, period="2026-08", source="eurostat", url="https://ec.europa.eu/x"
    )
    return NS(
        outlet=NS(name=outlet),
        indicator="paro",
        geo=geo,
        value=value,
        unit="pct",
        verification=NS(verdict=verdict, evidence=[ev]),
    )


def test_plain_words_differ_agree_and_latest():
    arts = [
        art("A", "2.000 detenidos y 350 agentes", 0),
        art("B", "2.000 detenidos y 350 agentes", 10),
        art("C", "2.400 detenidos", 60),
    ]
    p = in_plain_words(compare(arts), [])
    (d,) = p.differ
    assert (d["noun"], d["low"], d["high"], d["mode"], d["mode_n"]) == ("detenidos", 2000, 2400, 2000, 2)
    assert (d["latest"].outlet, d["latest"].value) == ("C", 2400)
    assert p.agree == [("agentes", 350, 2)] and not p.empty and p.n_outlets == 3
    assert in_plain_words(compare([art("A", "Sin cifras"), art("B", "Tampoco")]), []).empty


def test_truth_groups_outlets_by_official_figure():
    claims = [
        claim("A", 10.1, "verdadero"),
        claim("A", 10.0, "verdadero"),
        claim("B", 12.0, "falso"),
        claim("B", 12.5, "falso"),
        claim("C", 9.0, "sin-datos"),
        NS(outlet=NS(name="D"), verification=None),
    ]
    (t,) = truths_of(claims)
    assert t.official_text == "10,0 %" and t.right == ["A"] and t.wrong == [("B", "12,0 %", "falso")]
    assert len(truths_of([claim("A", 10, "verdadero"), claim("A", 10, "verdadero", geo="EU")])) == 2


def test_fmt():
    assert fmt(None) == "—" and fmt(1234.5) == "1.234,5" and fmt(2400.0) == "2.400"
    assert fmt(10.04, "pct") == "10,0 %"
