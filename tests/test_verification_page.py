from datetime import UTC, datetime
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from tests.test_web import client  # noqa: F401  (fixture)
from truthnews.models import Article, Claim, Evidence, Outlet, Story, Verification
from truthnews.web import verdicts

NOW = datetime.now(UTC)


def fake_claim(
    verdict, value=4.3, evidence=(("2026-08", 2.9, {"serie": {"2026-06": 2.3, "2026-07": 2.7}}),), **kw
):
    ev = [
        NS(value=v, period=p, source="ine", label="IPC", url="https://ine.es", payload=pl)
        for p, v, pl in evidence
    ]
    return NS(
        value=value,
        unit=kw.get("unit", "pct"),
        indicator="inflacion",
        direction=kw.get("direction"),
        outlet=NS(name="Diario <Ejemplo>", slug="d"),
        verification=NS(verdict=verdict, evidence=ev),
    )


@pytest.mark.parametrize(
    ("verdict", "expected"),
    [
        ("verdadero", "Verdadero: Diario <Ejemplo> dice 4,3 % y el dato oficial (2026-08, INE) es 2,9 %."),
        (
            "impreciso",
            "Impreciso: Diario <Ejemplo> dice 4,3 %; el dato oficial (2026-08, INE) es 2,9 %, 1,4 puntos",
        ),
        (
            "falso",
            "Falso: Diario <Ejemplo> dice 4,3 %, pero el dato oficial (2026-08, INE) es 2,9 %: 1,4 puntos",
        ),
    ],
)
def test_sentence_per_verdict(verdict, expected):
    assert verdicts.sentence(fake_claim(verdict)).startswith(expected)


def test_sentence_misleading_nodata_and_english():
    c = fake_claim("enganoso", direction="sube", evidence=(("2026-08", 2.9, {}), ("2026-07", 3.1, {})))
    assert verdicts.sentence(c) == (
        "Engañoso: Diario <Ejemplo> dice que «Inflación interanual» sube, pero el dato oficial baja "
        "(2026-07 → 2026-08, INE)."
    )
    assert verdicts.sentence(fake_claim("sin-datos", evidence=())).startswith("Sin datos suficientes")
    assert verdicts.sentence(fake_claim("falso"), "en").startswith("False: Diario <Ejemplo> says 4,3 %")
    abs_claim = fake_claim("falso", value=50_000_000, unit="abs", evidence=(("2025", 49_000_000, {}),))
    assert "2,0 %" in verdicts.sentence(abs_claim)


def test_chart_marks_the_claim_and_escapes():
    c = fake_claim("falso")
    pts = verdicts.series_of(c)
    assert pts == [("2026-06", 2.3), ("2026-07", 2.7), ("2026-08", 2.9)]
    svg = str(verdicts.chart(c))
    assert svg.startswith("<svg") and svg.count("<circle") == 3 and "stroke-dasharray" in svg
    assert "Diario &lt;Ejemplo&gt;: 4,3 %" in svg and "<Ejemplo>" not in svg
    assert "2026-08: 2,9 %" in svg  # valor al pasar el raton
    one = fake_claim("verdadero", value=2.9, evidence=(("2026-08", 2.9, {}),))
    assert str(verdicts.chart(one)).count("<circle") == 1  # un solo punto y sin linea
    assert str(verdicts.chart(fake_claim("sin-datos", evidence=()))) == ""


def test_verification_page_and_links(client, session):  # noqa: F811
    o = session.scalars(select(Outlet)).first()
    a = session.scalars(select(Article)).first()
    st = Story(
        title="Historia", category="economia", country="ES", first_seen=NOW, last_seen=NOW, n_outlets=2
    )
    session.add(st)
    session.flush()
    a.story_id = st.id
    c = Claim(
        article_id=a.id,
        story_id=st.id,
        outlet_id=o.id,
        text="La inflación se situó en el 4,3 % en agosto.",
        indicator="inflacion",
        geo="ES",
        value=4.3,
        unit="pct",
        extractor="ia",
        period="2026-08",
    )
    session.add(c)
    session.flush()
    v = Verification(
        claim_id=c.id, verdict="falso", confidence=0.8, explanation="Explicación.", method="nivel/v3"
    )
    v.evidence.append(
        Evidence(
            source="ine",
            label="IPC",
            url="https://ine.es/x",
            period="2026-08",
            value=2.9,
            payload={"serie": {"2026-07": 2.7, "2026-08": 2.9}},
        )
    )
    session.add(v)
    session.commit()
    r = client.get(f"/verificacion/{c.id}")
    assert r.status_code == 200
    html = r.text
    assert "Falso: Medio Uno dice 4,3 %, pero el dato oficial (2026-08, INE) es 2,9 %" in html
    assert (
        '<svg class="vchart"' in html and "share-whatsapp" in html and "validada por nuestras reglas" in html
    )
    assert f"/historia/{st.id}" in html
    assert client.get("/verificacion/999999").status_code == 404
    assert f"/verificacion/{c.id}" in client.get("/verificaciones").text
    assert f"/verificacion/{c.id}" in client.get(f"/historia/{st.id}").text


def test_evidence_keeps_the_last_points_of_the_series():
    from truthnews.analysis.pipeline import SERIES_POINTS, _store
    from truthnews.analysis.verify import Result
    from truthnews.data import Observation

    hist = {f"2025-{m:02d}": float(m) for m in range(1, 13)} | {
        f"2026-{m:02d}": 20.0 + m for m in range(1, 9)
    }
    obs = Observation(
        "ine", "IPC", "https://ine.es", "2026-08", 28.0, history=hist, extra={"serie_ine": "IPC290751"}
    )
    ver = Verification(claim_id=1)
    _store(ver, Result("verdadero", 0.9, "x", "nivel", [obs]))
    serie = ver.evidence[0].payload["serie"]
    assert len(serie) == SERIES_POINTS and max(serie) == "2026-08" and ver.evidence[0].payload["serie_ine"]
