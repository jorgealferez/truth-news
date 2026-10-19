from datetime import UTC, date, datetime

import pytest

from truthnews.analysis.claims import ClaimCandidate
from truthnews.analysis.verify import Verifier, applicable, default_fetch
from truthnews.data import Observation

NOW = datetime.now(UTC)
RECENT = f"{NOW.year}-{NOW.month:02d}" if NOW.month > 1 else f"{NOW.year - 1}-12"


def obs(value, period=RECENT, prev=None):
    o = Observation("eurostat", "Tasa de paro", "https://ec.europa.eu/x", period, value)
    if prev is not None:
        o.previous = Observation("eurostat", "Tasa de paro", "https://ec.europa.eu/x", "2000-01", prev)
    return o


def claim(value, indicator="paro", direction=None, unit="pct", geo="ES"):
    return ClaimCandidate("texto", indicator, geo, value, unit, direction)


@pytest.mark.parametrize(
    "claimed,official,verdict",
    [
        (10.0, 10.1, "verdadero"),
        (10.5, 10.0, "impreciso"),
        (12.5, 10.0, "falso"),
    ],
)
def test_level_verdicts(claimed, official, verdict):
    r = Verifier(lambda s, g, label: obs(official)).judge(claim(claimed))
    assert r.verdict == verdict and r.observations and "dato oficial" in r.explanation
    assert r.method.endswith("/v12")


def test_direction_misleading_and_consistent():
    v = Verifier(lambda s, g, label: obs(10.0, prev=11.0))
    r = v.judge(claim(10.0, direction="sube"))
    assert r.verdict == "enganoso" and len(r.observations) == 2
    assert v.judge(claim(10.0, direction="baja")).verdict == "verdadero"


def test_absolute_values():
    v = Verifier(lambda s, g, label: obs(49_355_143))
    assert v.judge(claim(49_300_000, "poblacion", unit="abs")).verdict == "verdadero"
    assert v.judge(claim(46_000_000, "poblacion", unit="abs")).verdict == "impreciso"
    assert v.judge(claim(40_000_000, "poblacion", unit="abs")).verdict == "falso"


def test_no_source_stale_and_failing_source():
    assert Verifier(lambda s, g, label: None).judge(claim(10)).verdict == "sin-datos"
    stale = Verifier(lambda s, g, label: obs(10.0, period="2019-01")).judge(claim(10))
    assert stale.verdict == "sin-datos" and stale.method == "dato-obsoleto/v12"

    def boom(s, g, label):
        raise RuntimeError("caida")

    assert Verifier(boom).judge(claim(10)).method == "sin-fuente/v12"


def test_cited_period_is_compared_with_that_period():
    hist = {"2026-07": 3.58, "2026-08": 4.28, "2026-09": 4.92}
    latest = Observation("ine", "IPC", "https://ine.es/x", "2026-09", 4.92, history=hist)
    v = Verifier(lambda s, g, label: latest)
    c = ClaimCandidate("el IPC del 4,3 % de agosto", "inflacion", "ES", 4.3, "pct", None, "2026-08")
    r = v.judge(c)
    assert (
        r.verdict == "verdadero"
        and r.observations[0].period == "2026-08"
        and "periodo citado" in r.explanation
    )
    up = ClaimCandidate("sube al 4,3 % en agosto", "inflacion", "ES", 4.3, "pct", "baja", "2026-08")
    assert v.judge(up).verdict == "enganoso"  # julio 3,58 -> agosto 4,28: sube
    gone = v.judge(ClaimCandidate("x", "inflacion", "ES", 4.3, "pct", None, "2020-01"))
    assert gone.verdict == "sin-datos" and gone.method == "sin-periodo/v12"
    assert latest.at("2026-07").previous is None


def test_cache_and_applicability():
    calls = []

    def fetch(s, g, label):
        calls.append(s["connector"])
        return obs(10.0)

    v = Verifier(fetch)
    v.judge(claim(10))
    v.judge(claim(10))
    assert calls == ["eurostat"]
    assert applicable({"connector": "eurostat", "geos": "EU"}, "FR")
    assert not applicable({"connector": "eurostat", "geos": "EU"}, "US")
    assert applicable({"connector": "ine_yoy", "geos": ["ES"]}, "ES")
    assert applicable({"connector": "worldbank"}, "EU")
    assert not applicable({"connector": "x"}, "EU")
    with pytest.raises(ValueError):
        default_fetch({"connector": "nada"}, "ES", "")


def test_observation_periods():
    assert Observation("s", "l", "u", "2026-Q2", 1).period_end() == date(2026, 6, 28)
    assert Observation("s", "l", "u", "2025", 1).period_end() == date(2025, 12, 31)
    assert Observation("s", "l", "u", "2025", 1).is_stale(date(2027, 3, 1))


def test_negated_series_for_deficit():
    from truthnews.analysis.verify import negated

    prev = Observation("eurostat", "B9", "https://x", "2024", -3.2)
    obs = Observation(
        "eurostat", "B9", "https://x", "2025", -2.4, previous=prev, history={"2024": -3.2, "2025": -2.4}
    )
    n = negated(obs)
    assert (n.value, n.previous.value, n.history) == (2.4, 3.2, {"2024": 3.2, "2025": 2.4})
    assert "signo" in n.extra and obs.value == -2.4 and negated(None) is None


def test_deficit_is_judged_against_the_negated_series(monkeypatch):
    from truthnews.analysis import verify as v
    from truthnews.analysis.claims import extract

    def fake_latest(dataset, geo, params, label=""):
        assert dataset == "gov_10dd_edpt1"
        return Observation("eurostat", label, "https://x", "2025", -2.4, history={"2025": -2.4})

    monkeypatch.setattr(v.eurostat, "latest", fake_latest)
    (claim,) = extract("El déficit público se situó en el 2,5 % del PIB.", "es", "ES", 2026)
    res = v.Verifier().judge(claim)
    assert res.verdict == "verdadero" and res.observations[0].value == 2.4


def test_threshold_has_no_floating_point_error():
    # Caso real (elDinero, 19/10/2026): Suecia 8,7 % frente a 8,9 % oficial = 0,2 puntos -> Verdadero.
    from truthnews.analysis.claims import ClaimCandidate

    v = Verifier(lambda s, g, label: Observation("eurostat", label, "https://x", "2026-08", 8.9))
    assert v.judge(ClaimCandidate("x", "paro", "SE", 8.7, "pct", None)).verdict == "verdadero"


def test_harmonised_inflation_does_not_judge_the_measure_gap(monkeypatch):
    # Caso real (La Gaceta de Salamanca, 19/10/2026): Francia 3,1 % frente al 3,4 % del IPCA.
    from truthnews.analysis import verify as v
    from truthnews.analysis.claims import ClaimCandidate

    monkeypatch.setattr(
        v.eurostat,
        "latest",
        lambda d, g, p, label="": Observation("eurostat", label, "https://x", "2026-09", 3.4),
    )
    judge = v.Verifier().judge
    gap = judge(ClaimCandidate("x", "inflacion", "FR", 3.1, "pct", None))
    assert gap.verdict == "sin-datos" and "IPC nacional" in gap.explanation and gap.observations
    assert judge(ClaimCandidate("x", "inflacion", "FR", 3.4, "pct", None)).verdict == "verdadero"
    assert judge(ClaimCandidate("x", "inflacion", "FR", 5.0, "pct", None)).verdict == "falso"


def test_public_debt_is_never_judged_against_central_government_debt():
    from truthnews.analysis.claims import indicators

    sources = indicators()["deuda_publica"]["sources"]
    assert all(not s.get("indicator", "").startswith("GC.") for s in sources)
    assert not any(applicable(s, "US") for s in sources)  # fuera de la UE: sin serie, sin juicio
    calls = []
    res = Verifier(lambda s, g, label: calls.append(s) or obs(120.0)).judge(
        claim(123.0, indicator="deuda_publica", geo="US")
    )
    assert calls == [] and res.verdict == "sin-datos" and res.method == "sin-fuente/v12"


def test_approximate_figure_within_the_wide_band_is_true():
    v = Verifier(lambda s, g, label: obs(41_500_000))

    def pop(text, value):
        return ClaimCandidate(text, "poblacion", "CA", value, "abs", None)

    approx = v.judge(pop("Canadá tiene unos 40 millones de habitantes.", 40e6))
    assert approx.verdict == "verdadero" and approx.method == "aproximado/v12"
    assert v.judge(pop("Canadá tiene 40 millones de habitantes.", 40e6)).verdict == "impreciso"
    assert v.judge(pop("Canadá tiene unos 30 millones de habitantes.", 30e6)).verdict == "falso"


def test_euribor_is_judged_against_the_ecb_monthly_average(monkeypatch):
    from truthnews.analysis import verify as v
    from truthnews.analysis.claims import extract

    def fake_latest(flow, key, label=""):
        assert (flow, key) == ("FM", "M.U2.EUR.RT.MM.EURIBOR1YD_.HSTA")
        return Observation(
            "ecb", label, "https://data.ecb.europa.eu/x", RECENT, 3.247, history={RECENT: 3.247}
        )

    monkeypatch.setattr(v.ecb, "latest", fake_latest)
    judge = v.Verifier().judge
    assert judge(claim(3.2, indicator="euribor")).verdict == "verdadero"
    # Sin periodo puede ser el valor diario: la franja dudosa no se juzga (otra medida).
    daily = judge(claim(2.9, indicator="euribor"))
    assert daily.verdict == "sin-datos" and "valor diario" in daily.explanation
    assert judge(claim(1.5, indicator="euribor")).verdict == "falso"
    # Extraccion (fechas fijas: no depende del dia en que se ejecuta el test).
    sep = extract("El Euríbor de septiembre se situó en el 3,2 %.", "es", "ES", 2026, 10)
    assert [(c.indicator, c.period) for c in sep] == [("euribor", "2026-09")]
    assert extract("El Euríbor a tres meses se sitúa en el 2,1 %.", "es", "ES", 2026, 10) == []


def test_v12_published_unfair_falsos_are_not_judged(monkeypatch):
    """Casos reales del 19/10/2026 publicados como Falso con v11 (revision manual de /verificaciones)."""
    from truthnews.analysis import verify as v

    # La Nacion: Argentina "211 % en 2023" (diciembre/diciembre) frente a la media anual del Banco Mundial.
    def wb(indicator, geo, label=""):
        hist = {"2022": 72.4, "2023": 133.5, "2024": 219.9}
        return Observation("worldbank", label, "https://x", "2024", 219.9, history=hist)

    monkeypatch.setattr(v.worldbank, "latest", wb)
    judge = v.Verifier().judge
    ar = judge(ClaimCandidate("x", "inflacion", "AR", 211.0, "pct", None, "2023"))
    assert ar.verdict == "sin-datos" and ar.method == "otra-medida/v12" and "diciembre" in ar.explanation
    assert judge(ClaimCandidate("x", "inflacion", "AR", 133.5, "pct", None, "2023")).verdict == "verdadero"
    # The Guardian: deuda de Francia 119 % (T2 del INSEE) frente a Eurostat 2026-Q1 117,6 %.
    hist = {"2025-Q2": 115.4, "2025-Q3": 117.3, "2025-Q4": 115.7, "2026-Q1": 117.6}
    fr = Verifier(lambda s, g, label: Observation("eurostat", label, "u", "2026-Q1", 117.6, history=hist))
    later = fr.judge(claim(119.0, indicator="deuda_publica", geo="FR"))
    assert later.verdict == "sin-datos" and later.method == "periodo-posterior/v12"
    # Una diferencia mayor que cualquier cambio entre trimestres si se juzga.
    assert fr.judge(claim(130.0, indicator="deuda_publica", geo="FR")).verdict == "falso"
    # Serie mensual: el siguiente dato llega pronto, no se aplica.
    monthly = Verifier(lambda s, g, label: Observation("e", label, "u", RECENT, 10.0, history={RECENT: 10.0}))
    assert monthly.judge(claim(12.5)).verdict == "falso"


def test_v12_assumed_country_in_a_story_about_another_never_accuses():
    v = Verifier(lambda s, g, label: obs(10.0))
    doubtful = ClaimCandidate("texto", "paro", "ES", 7.9, "pct", None, doubtful_geo=True)
    r = v.judge(doubtful)
    assert r.verdict == "sin-datos" and r.method == "pais-supuesto/v12" and r.observations
    # Puede decir que cuadra.
    ok = ClaimCandidate("texto", "paro", "ES", 10.0, "pct", None, doubtful_geo=True)
    assert v.judge(ok).verdict == "verdadero"
