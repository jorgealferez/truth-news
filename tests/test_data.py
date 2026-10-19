import json
from datetime import date

import httpx

from truthnews.data import boe, eurostat, gdelt, ine, worldbank


def transport(routes: dict):
    def handler(request: httpx.Request):
        for key, resp in routes.items():
            if key in str(request.url):
                return resp
        return httpx.Response(404)

    return httpx.MockTransport(handler)


EUROSTAT = {
    "label": "Unemployment",
    "updated": "2026-10-16",
    "id": ["freq", "geo", "time"],
    "size": [1, 1, 3],
    "dimension": {"time": {"category": {"index": {"2026-07": 0, "2026-08": 1, "2026-09": 2}}}},
    "value": {"0": 10.1, "1": 10.0},
}


def test_eurostat_latest_skips_empty_periods_and_maps_geo():
    t = transport({"une_rt_m": httpx.Response(200, json=EUROSTAT)})
    o = eurostat.latest("une_rt_m", "GR", {"unit": "PC_ACT"}, "Paro", transport=t)
    assert (o.period, o.value, o.previous.value) == ("2026-08", 10.0, 10.1)
    assert o.history == {"2026-07": 10.1, "2026-08": 10.0} and o.at("2026-07").value == 10.1
    assert "geo=EL" in o.url and o.extra["dataset"] == "une_rt_m"

    def ea_only20(request):
        if "geo=EA20" in str(request.url):
            return httpx.Response(200, json=EUROSTAT)
        return httpx.Response(200, json={**EUROSTAT, "value": {}})

    ea = eurostat.latest("une_rt_m", "EA", {}, transport=httpx.MockTransport(ea_only20))
    assert "geo=EA20" in ea.url  # EA21 sin datos -> se prueba el siguiente codigo


def test_eurostat_rejects_ambiguous_and_errors():
    amb = {**EUROSTAT, "size": [1, 2, 3]}
    assert eurostat.latest("x", "ES", {}, transport=transport({"x": httpx.Response(200, json=amb)})) is None
    assert eurostat.latest("x", "ES", {}, transport=transport({})) is None
    assert (
        eurostat.latest("x", "ES", {}, transport=transport({"x": httpx.Response(200, json={"error": 1})}))
        is None
    )
    empty = {**EUROSTAT, "value": {}}
    assert eurostat.latest("x", "ES", {}, transport=transport({"x": httpx.Response(200, json=empty)})) is None


def test_worldbank():
    body = [
        {"page": 1},
        [
            {"indicator": {"value": "Population"}, "date": "2025", "value": 49355143},
            {"indicator": {"value": "Population"}, "date": "2024", "value": 48800000},
            {"indicator": {"value": "Population"}, "date": "2023", "value": None},
        ],
    ]
    o = worldbank.latest("SP.POP.TOTL", "ES", transport=transport({"SP.POP": httpx.Response(200, json=body)}))
    assert (o.period, o.value, o.previous.period) == ("2025", 49355143.0, "2024")
    assert (
        worldbank.latest("X", "EU", transport=transport({"EUU": httpx.Response(200, json=[{}, []])})) is None
    )
    assert worldbank.latest("X", "ES", transport=transport({})) is None


def test_ine_annual_change_uses_period_fields():
    data = {
        "Nombre": "IPC Índice general",
        "Data": [
            {"Fecha": 0, "Anyo": 2025, "FK_Periodo": 9, "Valor": 100.0, "Secreto": False},
            {"Fecha": 0, "Anyo": 2026, "FK_Periodo": 9, "Valor": 104.9, "Secreto": False},
            {"Fecha": 0, "Anyo": 2026, "FK_Periodo": 10, "Valor": None, "Secreto": False},
        ],
    }
    o = ine.annual_change("IPC290751", transport=transport({"IPC290751": httpx.Response(200, json=data)}))
    assert (o.period, o.value) == ("2026-09", 4.9) and o.history == {"2026-09": 4.9}
    assert ine.annual_change("X", transport=transport({})) is None
    one = {"Nombre": "x", "Data": [data["Data"][1]]}
    assert ine.annual_change("Y", transport=transport({"Y": httpx.Response(200, json=one)})) is None


def test_boe_search():
    body = {
        "data": {
            "sumario": {
                "diario": [
                    {
                        "seccion": [
                            {
                                "item": [
                                    {
                                        "identificador": "BOE-A-1",
                                        "titulo": "Real Decreto 707/2026 de accesibilidad cognitiva",
                                        "url_html": "https://boe.es/1",
                                    },
                                    {
                                        "identificador": "BOE-A-2",
                                        "titulo": "Orden de pesca",
                                        "url_pdf": {"texto": "https://boe.es/2.pdf"},
                                    },
                                ]
                            }
                        ]
                    }
                ]
            }
        }
    }
    t = transport({"sumario/20261016": httpx.Response(200, json=body)})
    assert len(boe.sumario(date(2026, 10, 16), transport=t)) == 2
    hits = boe.search(date(2026, 10, 16), "real decreto accesibilidad", transport=t)
    assert [h["id"] for h in hits] == ["BOE-A-1"]
    assert boe.search(date(2026, 10, 16), "y de", transport=t) == []
    assert boe.sumario(date(2026, 10, 17), transport=t) == []


def test_gdelt_respects_rate_limit():
    waits = []
    ok = httpx.Response(
        200,
        json={"timeline": [{"data": [{"date": "x", "value": 0.1}]}]},
        headers={"content-type": "application/json"},
    )
    t = transport({"timelinevol": ok})
    assert gdelt.timeline("riots", transport=t, sleep=waits.append) == [{"date": "x", "value": 0.1}]
    gdelt.timeline("riots", transport=t, sleep=waits.append)
    assert waits and waits[-1] > 4
    calls = []

    def limited(request):
        calls.append(1)
        return httpx.Response(429, text="Please limit requests") if len(calls) == 1 else ok

    assert gdelt.timeline("x", transport=httpx.MockTransport(limited), sleep=lambda s: None) == [
        {"date": "x", "value": 0.1}
    ]
    assert len(calls) == 2
    text = httpx.Response(200, text="Please limit requests", headers={"content-type": "text/html"})
    assert gdelt.timeline("x", transport=transport({"timelinevol": text}), sleep=lambda s: None) == []
    assert json.dumps(waits)


def test_ine_level_reads_quarters():
    # Formato real de la EPA (tabla 65334): FK_Periodo 19-22 son los trimestres.
    data = {
        "Nombre": "Tasa de paro de la población. Ambos sexos. Andalucía. Total. ",
        "Data": [
            {"Anyo": 2025, "FK_Periodo": 22, "Valor": 14.66, "Secreto": False},
            {"Anyo": 2026, "FK_Periodo": 19, "Valor": 14.66, "Secreto": False},
            {"Anyo": 2026, "FK_Periodo": 20, "Valor": 14.56, "Secreto": False},
        ],
    }
    o = ine.level("EPA452440", transport=transport({"EPA452440": httpx.Response(200, json=data)}))
    assert (o.period, o.value, o.previous.period) == ("2026-Q2", 14.56, "2026-Q1")
    assert list(o.history) == ["2025-Q4", "2026-Q1", "2026-Q2"] and o.extra["serie"] == "EPA452440"
    assert ine.level("X", transport=transport({})) is None
