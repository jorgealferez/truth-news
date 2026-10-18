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
    assert stale.verdict == "sin-datos" and stale.method == "dato-obsoleto"

    def boom(s, g, label):
        raise RuntimeError("caida")

    assert Verifier(boom).judge(claim(10)).method == "sin-fuente"


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
