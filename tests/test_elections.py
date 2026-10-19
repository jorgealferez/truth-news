"""Elecciones (ADR 0036): convocatorias reales del BOE, registro, medios y la seccion temporal."""

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from truthnews.config import Settings
from truthnews.elections import calendar as cal
from truthnews.elections import views
from truthnews.models import PoliticalStatement, StatementCheck, Story
from truthnews.registry import RegistryError
from truthnews.web.app import create_app

FIX = Path(__file__).parent / "fixtures"
SUMARIO = json.loads((FIX / "boe_sumario_20261006_elecciones.json").read_text())
DECREE = (FIX / "boe_rd_806_2026.html").read_text()


def test_real_convocation_is_found_and_parsed():
    found = cal.convocations(SUMARIO)
    assert [f["id"] for f in found] == ["BOE-A-2026-20742"]  # el resto del sumario no es una convocatoria
    item = found[0]
    assert item["kind"] == "generales" and item["region"] is None
    assert item["departamento"] == "JEFATURA DEL ESTADO"
    e = cal.from_boe(item, DECREE, date(2026, 10, 6))
    assert e.date == date(2026, 11, 29) and e.status == "convocada"
    assert e.campaign == (date(2026, 11, 13), date(2026, 11, 27))
    assert e.constitution == date(2026, 12, 23) and e.convened == date(2026, 10, 6)
    assert e.slug == "es-generales-2026-11-29" and e.name == "Elecciones generales"
    assert e.sources[0].url.endswith("BOE-A-2026-20742")


def test_scope_needs_an_elected_body():
    assert cal.scope_of("Resolución por la que se convocan elecciones sindicales en la empresa X.") is None
    assert cal.scope_of("Orden de convocatoria de elecciones a la Cámara de Comercio de Soria.") is None
    assert cal.scope_of("Real Decreto de convocatoria de elecciones al Parlamento Europeo.") == "europeas"
    t = "Decreto 2/2026, de disolución del Parlamento de Andalucía y de convocatoria de elecciones."
    assert cal.scope_of(t) == "autonomicas" and cal.region_of(t) == "ES-AN"
    assert cal.region_of("Decreto de convocatoria de elecciones al Parlamento Vasco.") == "ES-PV"
    assert cal.region_of("Castilla y León y Castilla-La Mancha") is None  # ambiguo: no se adivina
    local = {
        "id": "BOE-A-1",
        "titulo": "Real Decreto 9/2026, por el que se convocan nuevas elecciones locales en el municipio "
        "de Villanueva del Río, de la provincia de Sevilla.",
        "url": "u",
        "kind": "locales",
        "region": None,
    }
    e = cal.from_boe(local, "Las elecciones se celebrarán el día 14 de febrero.", date(2026, 1, 2))
    assert e.place == "Villanueva del Río" and e.date == date(2026, 2, 14)
    assert e.name == "Elecciones locales · Villanueva del Río"


def test_decree_without_poll_date_is_ignored_and_year_rolls_over():
    assert cal.parse_decree("Se convocan elecciones.", date(2026, 1, 1)) == {}
    out = cal.parse_decree("Las elecciones se celebrarán el domingo 10 de enero.", date(2026, 11, 20))
    assert out["date"] == date(2027, 1, 10)


def test_registry_is_valid_and_matches_the_boe():
    reg = cal.load_registry()
    boe = cal.from_boe(cal.convocations(SUMARIO)[0], DECREE, date(2026, 10, 6))
    assert [e.key for e in reg] == [boe.key]
    assert (reg[0].campaign, reg[0].constitution) == (boe.campaign, boe.constitution)
    merged = cal.merge([boe], reg)
    assert len(merged) == 1 and len(merged[0].sources) == 1  # misma URL: una sola cita
    with pytest.raises(RegistryError):
        cal.load_registry({"elections": [{"country": "ES", "kind": "generales", "date": "2027-01-01"}]})
    with pytest.raises(RegistryError):
        cal.load_registry({"elections": [{"country": "ES", "kind": "x", "date": "2027-01-01"}]})


def test_window_and_phases():
    e = cal.load_registry()[0]
    assert not e.in_window(date(2026, 10, 5)) and e.in_window(date(2026, 10, 6))
    assert e.in_window(date(2026, 12, 29)) and not e.in_window(date(2026, 12, 30))
    assert e.phase(date(2026, 10, 19)) == "precampana" and e.days_left(date(2026, 10, 19)) == 41
    assert e.phase(date(2026, 11, 13)) == "campana" and e.phase(date(2026, 11, 28)) == "reflexion"
    assert e.phase(date(2026, 11, 29)) == "jornada" and e.phase(date(2026, 12, 1)) == "celebrada"


def _art(i, title, outlet, when):
    return SimpleNamespace(
        title=title,
        outlet_id=outlet,
        outlet=SimpleNamespace(name=f"Medio {outlet}"),
        url=f"https://m{outlet}.example/{i}",
        published_at=when,
    )


def test_press_needs_two_outlets_same_country_and_date():
    now = datetime(2026, 10, 19, tzinfo=UTC)
    arts = [
        _art(1, "Portugal celebrará elecciones legislativas el 13 de diciembre", 1, now),
        _art(2, "Elecciones en Portugal: los partidos se preparan para el 13 de diciembre", 2, now),
        _art(3, "Portugal irá a elecciones el 13 de diciembre", 2, now),
        _art(4, "Elecciones en Francia el 8 de marzo", 3, now),  # un solo medio: no basta
        _art(5, "Portugal y Francia, elecciones el 8 de marzo", 4, now),  # dos paises: ambiguo
        _art(6, "Partido de futbol en Portugal el 13 de diciembre", 5, now),  # sin elecciones
    ]
    hits = cal.press_hits(arts, now.date())
    assert len(hits) == 1
    e = hits[0]
    assert (e.country, e.date, e.kind, e.status) == ("PT", date(2026, 12, 13), "legislativas", "anunciada")
    assert e.name == "Elecciones legislativas · Portugal" and len(e.sources) == 3
    # Lo anunciado en medios cede ante una convocatoria oficial del mismo pais y dia.
    official = cal.Election("PT", "legislativas", e.date, "x", "convocada", (cal.Source("d", "u"),))
    assert cal.merge([official], hits) == [official]


def _transport(calls):
    def handler(request):
        calls.append(str(request.url))
        if "sumario/20261006" in str(request.url):
            return httpx.Response(200, json=SUMARIO)
        if "txt.php" in str(request.url):
            return httpx.Response(200, text=DECREE)
        if "sumario/20261007" in str(request.url):
            return httpx.Response(503)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_calendar_scans_the_boe_and_caches_past_days():
    calls = []
    c = cal.Calendar(14, transport=_transport(calls), background=False, registry_raw={"elections": []})
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    active = c.active(None, now)
    assert [e.slug for e in active] == ["es-generales-2026-11-29"]
    assert not any("sumario/20261018" in u for u in calls)  # domingo: no hay BOE
    n = len(calls)
    c.warm(now.date(), pause=0)
    # Dias pasados con respuesta ya no se piden; los ultimos dias y el que fallo (503) se reintentan.
    again = calls[n:]
    assert not any("20261006" in u for u in again) and all("txt.php" not in u for u in again)
    assert c.get("es-generales-2026-11-29", None, now).campaign[0] == date(2026, 11, 13)
    assert c.get("nada", None, now) is None
    assert c.active(None, datetime(2027, 3, 1, tzinfo=UTC)) == []  # fuera de ventana: no hay seccion


def test_calendar_with_lookback_zero_uses_only_the_registry():
    c = cal.Calendar(0)
    assert c.boe() == [] and [e.slug for e in c.all(None, datetime(2026, 10, 19, tzinfo=UTC))] == [
        "es-generales-2026-11-29"
    ]


def _statement(session, actor, text, when, url):
    st = PoliticalStatement(
        actor=actor,
        country="ES",
        channel="web",
        url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        text=text,
        published_at=when,
    )
    session.add(st)
    session.flush()
    return st


def _near_registry(today: date) -> dict:
    return {
        "elections": [
            {
                "country": "ES",
                "kind": "generales",
                "name": "Elecciones generales",
                "date": (today + timedelta(days=20)).isoformat(),
                "convened": (today - timedelta(days=10)).isoformat(),
                "campaign": [str(today + timedelta(days=4)), str(today + timedelta(days=18))],
                "source": {"label": "Real Decreto de prueba", "url": "https://www.boe.es/x"},
                "programs": {"sumar": "https://movimientosumar.es/programa"},
            }
        ]
    }


def test_election_pages(engine, session):
    now = datetime.now(UTC)
    slug = f"es-generales-{(now.date() + timedelta(days=20)).isoformat()}"
    pp = _statement(session, "pp", "Bajaremos el IRPF", now - timedelta(days=1), "https://pp.example/1")
    _statement(session, "vox", "Antes de la convocatoria", now - timedelta(days=30), "https://vox.example/1")
    session.add(
        StatementCheck(
            statement_id=pp.id,
            text="paro del 10 %",
            indicator="paro",
            geo="ES",
            value=10.0,
            unit="%",
            verdict="falso",
            confidence=0.9,
            explanation="x",
            method="m",
            evidence=[],
        )
    )
    session.add(
        Story(
            title="La campaña de las elecciones generales arranca con encuestas",
            category="politica",
            country="ES",
            first_seen=now - timedelta(days=2),
            last_seen=now - timedelta(hours=1),
        )
    )
    session.add(
        Story(
            title="Sube el precio de la luz",
            category="economia",
            country="ES",
            first_seen=now - timedelta(days=2),
            last_seen=now - timedelta(hours=1),
        )
    )
    session.commit()
    elections = cal.Calendar(0, registry_raw=_near_registry(now.date()))
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine, elections=elections))

    home = client.get("/").text
    assert f'href="/elecciones/{slug}"' in home  # enlace temporal en la cabecera

    r = client.get("/elecciones")
    assert r.status_code == 200 and f"/elecciones/{slug}" in r.text and "faltan 20 días" in r.text

    r = client.get(f"/elecciones/{slug}")
    assert r.status_code == 200
    page = r.text
    assert "Real Decreto de prueba" in page and "Precampaña" in page
    assert "Bajaremos el IRPF" in page and "Antes de la convocatoria" not in page
    assert "Falso 1" in page and "https://movimientosumar.es/programa" in page
    # Los 12 partidos del registro con el mismo formato; solo uno tiene programa enlazado.
    assert page.count("no localizado aún") == 11
    assert "arranca con encuestas" in page and "precio de la luz" not in page
    assert 'class="ad' not in page  # sin publicidad
    assert client.get("/elecciones/es-generales-1999-01-01").status_code == 404
    en = client.get(f"/en/elecciones/{slug}")
    assert en.status_code == 200 and "What the parties say" in en.text


def test_no_section_without_elections(engine):
    elections = cal.Calendar(0, registry_raw={"elections": []})
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine, elections=elections))
    assert "el-nav" not in client.get("/").text
    r = client.get("/elecciones")
    assert r.status_code == 200 and "no hay elecciones convocadas" in r.text


def test_regional_election_filters_by_territory(session):
    now = datetime(2026, 3, 1, tzinfo=UTC)
    e = cal.Election(
        "ES",
        "autonomicas",
        date(2026, 3, 15),
        "Elecciones autonómicas · Andalucía",
        "convocada",
        (cal.Source("d", "u"),),
        region="ES-AN",
        convened=date(2026, 1, 20),
    )
    _statement(session, "pp", "Propuestas para Andalucía", now - timedelta(days=2), "https://pp.example/a")
    _statement(session, "pp", "Propuestas para Galicia", now - timedelta(days=2), "https://pp.example/g")
    session.commit()
    rows = {p["actor"].slug: p for p in views.parties(session, e)}
    assert [s.text for s in rows["pp"]["statements"]] == ["Propuestas para Andalucía"]
    assert [d["key"] for d in views.key_dates(e, now.date())] == ["el_convened", "el_poll"]
