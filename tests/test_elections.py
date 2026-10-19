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
    assert e.phase(now.date()) == "proxima"  # sin campana conocida no se dice "precampana"
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
    ctx = Story(title="El Gobierno sube el IRPF a las rentas altas", category="economia", country="ES",
                first_seen=now - timedelta(days=2), last_seen=now - timedelta(days=1))
    session.add(ctx)
    session.flush()
    pp = _statement(session, "pp", "Bajaremos el IRPF", now - timedelta(days=1), "https://pp.example/1")
    pp.story_id = ctx.id
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
    assert "lo dijo a propósito de" in page and "El Gobierno sube el IRPF" in page
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
    assert 'id="elecciones"' in client.get("/metodologia").text


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


CANDS = (FIX / "boe_candidaturas_2023_extracto.html").read_text()


def test_candidacies_from_the_real_2023_boe():
    from truthnews.elections import candidacies

    fs = candidacies.parse(CANDS)
    by = {f.acronym: f for f in fs}
    assert len(fs) == 12 and fs[0].acronym == "PP"  # de la que mas circunscripciones cubre a la que menos
    assert by["PP"].congreso == ["Albacete", "Las Palmas", "Ceuta"]
    assert by["PP"].senado == ["Albacete", "Fuerteventura", "Gran Canaria", "Lanzarote", "Ceuta"]
    assert by["PSOE"].heads["Albacete"] == "Emilio Sáez Cruz"
    # Siglas con minusculas y candidatos con apodo entre parentesis no se confunden.
    assert by["NC-bc"].name == "NUEVA CANARIAS - BLOQUE CANARISTA" and by["CCa"].congreso == ["Las Palmas"]
    assert not any("Menchi" in f.name for f in fs)
    assert by["FO"].senado == []
    t = "Candidaturas proclamadas para las elecciones al Congreso ... convocadas por Real Decreto 400/2023."
    assert candidacies.kind_of(t) == "proclamadas" and candidacies.kind_of("Otra cosa") is None


def test_calendar_reads_candidacies_and_page_lists_every_party(engine):
    item = {
        "identificador": "BOE-A-2026-99999",
        "titulo": "Candidaturas proclamadas para las elecciones al Congreso de los Diputados y al Senado, "
        "convocadas por Real Decreto 806/2026, de 5 de octubre.",
        "url_html": "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-99999",
    }
    sumario = {
        "data": {
            "sumario": {
                "diario": [
                    {
                        "seccion": [
                            {"departamento": [{"nombre": "JUNTAS ELECTORALES PROVINCIALES", "item": item}]}
                        ]
                    }
                ]
            }
        }
    }

    def handler(request):
        url = str(request.url)
        if "sumario" in url:  # cualquier dia (los domingos no se piden): el mismo documento una vez
            return httpx.Response(200, json=sumario)
        if "BOE-A-2026-99999" in url:
            return httpx.Response(200, text=CANDS)
        return httpx.Response(404)

    today = datetime.now(UTC).date()
    reg = {
        "elections": [
            {
                "country": "ES",
                "kind": "generales",
                "date": str(today + timedelta(days=20)),
                "convened": str(today - timedelta(days=10)),
                "source": {"label": "Real Decreto 806/2026, de 5 de octubre (BOE-A-2026-20742)", "url": "u"},
            }
        ]
    }
    calls = []
    transport = httpx.MockTransport(lambda r: calls.append(str(r.url)) or handler(r))
    c = cal.Calendar(3, transport=transport, background=False, registry_raw=reg)
    e = c.active()[0]
    data = c.candidacies(e)
    assert data["kind"] == "proclamadas" and data["id"] == "BOE-A-2026-99999"
    assert len(data["formations"]) == 12
    assert sum("BOE-A-2026-99999" in u for u in calls) == 1  # el documento se lee una sola vez
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine, elections=c))
    page = client.get(f"/elecciones/{e.slug}").text
    assert "Candidaturas proclamadas" in page and "12 formaciones" in page
    assert 'href="#partido-pp"' in page and "NUEVA CANARIAS - BLOQUE CANARISTA" in page
    assert "Emilio Sáez Cruz" in page


def _check(session, st, value, period="2025", verdict="verdadero", indicator="paro"):
    session.add(
        StatementCheck(
            statement_id=st.id,
            text=f"el paro es del {value} %",
            indicator=indicator,
            geo="ES",
            value=value,
            unit="pct",
            period=period,
            verdict=verdict,
            confidence=0.9,
            explanation="x",
            method="m",
            evidence=[],
        )
    )


def test_figure_changes_need_same_period_and_a_real_gap(engine, session):
    now = datetime.now(UTC)
    poll = now.date() + timedelta(days=20)
    e = cal.Election("ES", "generales", poll, "x", "convocada", (cal.Source("d", "u"),))
    a = _statement(session, "pp", "El paro es del 10,5 %", now - timedelta(days=40), "https://pp.example/a")
    b = _statement(session, "pp", "El paro es del 12,9 %", now - timedelta(days=3), "https://pp.example/b")
    c = _statement(session, "vox", "El paro es del 11,0 %", now - timedelta(days=40), "https://vox.example/a")
    d = _statement(session, "vox", "El paro es del 11,2 %", now - timedelta(days=3), "https://vox.example/b")
    f = _statement(session, "sumar", "El paro es del 11 %", now - timedelta(days=3), "https://sumar.example/a")
    _check(session, a, 10.5)
    _check(session, b, 12.9)
    _check(session, c, 11.0)
    _check(session, d, 11.2)  # 0,2 puntos: redondeo, no cambio
    _check(session, f, 8.0, period="2019")
    session.commit()
    out = views.figure_changes(session, e, ["pp", "vox", "sumar"], now)
    assert list(out) == ["pp"]
    fc = out["pp"][0]
    assert fc["before"][1].url.endswith("/a") and fc["after"][0].value == 12.9
    reg = {"elections": [{"country": "ES", "kind": "generales", "date": str(poll),
                          "convened": str(now.date() - timedelta(days=5)),
                          "source": {"label": "Decreto", "url": "https://www.boe.es/x"}}]}
    elections = cal.Calendar(0, registry_raw=reg)
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine, elections=elections))
    page = client.get(f"/elecciones/es-generales-{poll.isoformat()}").text
    assert "Cifras que ha cambiado" in page and "Mismo dato y mismo periodo (2025)" in page


def test_jec_ongoing_elections_respect_visit_time():
    markup = (FIX / "jec_elecciones_en_curso_20261019.html").read_text()
    found = cal.from_jec(markup)
    assert [(e.kind, e.date, e.region) for e in found] == [("generales", date(2026, 11, 29), None)]
    assert found[0].sources[0].url.startswith("https://www.juntaelectoralcentral.es/cs/jec/eleccionesEnCurso/")
    extra = cal.from_jec(
        '<h3>Elecciones en curso</h3><ul>'
        '<li><a href="/a">Parlamento de Andalucía, 17 de mayo de 2026</a></li>'
        '<li><a href="/b">Comisión sin fecha</a></li>'
        '<li><a href="/c">Asamblea de Ninguna, 1 de mayo de 2026</a></li>'
    )
    assert [(e.kind, e.region) for e in extra] == [("autonomicas", "ES-AN")]  # sin territorio no se adivina
    assert cal.jec_in_window(21) and cal.jec_in_window(6) and not cal.jec_in_window(7)
    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "www.juntaelectoralcentral.es":
            return httpx.Response(200, text=markup)
        return httpx.Response(404)

    transport = httpx.MockTransport(handler)
    c = cal.Calendar(1, transport=transport, background=False, registry_raw={"elections": []})
    c.warm(date(2026, 10, 19), pause=0, hour=12)  # fuera de la franja de su robots.txt: no se pide
    assert "www.juntaelectoralcentral.es" not in calls
    c.warm(date(2026, 10, 19), pause=0, hour=22)
    merged = c.all(None, datetime(2026, 10, 19, 22, tzinfo=UTC))
    assert [e.slug for e in merged] == ["es-generales-2026-11-29"]
    c.warm(date(2026, 10, 19), pause=0, hour=23)  # una vez cada 12 h
    assert calls.count("www.juntaelectoralcentral.es") == 1


def test_world_calendar_declared_dates_only_and_spain_first(engine, session):
    markup = (FIX / "electionguide_upcoming_20261019.html").read_text()
    found, unknown = cal.from_world(markup)
    assert {(e.country, e.kind, e.date) for e in found} == {
        ("BG", "presidenciales", date(2026, 10, 25)),
        ("BR", "presidenciales", date(2026, 10, 25)),
        ("IL", "legislativas", date(2026, 10, 27)),
        ("US", "legislativas", date(2026, 11, 3)),
    }
    assert unknown == [] and not any(e.country == "GW" for e in found)  # "(t)": tentativa, no cuenta
    assert {e.status for e in found} == {"declarada"}
    merged = cal.merge(cal.load_registry(), found)
    us = next(e for e in merged if e.country == "US")
    assert len(us.sources) == 2 and us.name == "Elecciones legislativas · Estados Unidos"
    assert next(e for e in merged if e.country == "BG").name == "Elecciones presidenciales · Bulgaria"
    # Las generales de Espana en el calendario mundial no duplican las del BOE.
    spain = cal.Election("ES", "legislativas", date(2026, 11, 29), "x", "convocada", (cal.Source("w", "w"),))
    assert [e.kind for e in cal.merge(cal.load_registry(), [spain])] == ["generales"]
    assert cal.iso_of("United States of America") == "US" and cal.iso_of("Narnia") is None

    calls = []

    def handler(request):
        calls.append(request.url.host)
        if request.url.host == "www.electionguide.org":
            return httpx.Response(200, text=markup)
        return httpx.Response(404)

    c = cal.Calendar(1, transport=httpx.MockTransport(handler), background=False)
    now = datetime(2026, 10, 19, 12, tzinfo=UTC)
    c.warm(now.date(), pause=0, hour=12)
    c.warm(now.date(), pause=0, hour=12)
    assert calls.count("www.electionguide.org") == 1
    session.add(
        Story(title="Elecciones en Brasil: Lula y el segundo turno", category="internacional", country="ES",
              first_seen=now, last_seen=now)
    )
    session.add(
        Story(title="Elecciones generales: arranca la precampaña", category="politica", country="ES",
              first_seen=now, last_seen=now)
    )
    session.commit()
    br = c.get("br-presidenciales-2026-10-25", None, now)
    titles = [s.title for s in views.coverage(session, br, now)]
    assert titles == ["Elecciones en Brasil: Lula y el segundo turno"]


def test_nav_prefers_spain_and_links_the_world(engine):
    today = datetime.now(UTC).date()
    poll = today + timedelta(days=20)
    reg = {"elections": [{"country": "ES", "kind": "generales", "date": str(poll),
                          "convened": str(today - timedelta(days=5)),
                          "source": {"label": "Decreto", "url": "https://www.boe.es/x"}}]}
    elections = cal.Calendar(0, registry_raw=reg)
    src = (cal.Source("IFES", "https://www.electionguide.org/elections/id/1/"),)
    name = "Elecciones presidenciales · Brasil"
    other = cal.Election("BR", "presidenciales", today + timedelta(days=6), name, "declarada", src)
    elections._world = (0.0, [other])
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine, elections=elections))
    home = client.get("/").text
    assert f'href="/elecciones/es-generales-{poll.isoformat()}"' in home and "Elecciones en el mundo" in home
    index = client.get("/elecciones").text
    main = index[index.index("<main"):]
    assert main.index("Elecciones generales") < main.index("presidenciales · Brasil")  # Espana primero
    page = client.get(f"/elecciones/br-presidenciales-{(today + timedelta(days=6)).isoformat()}").text
    assert "IFES" in page and "Qué dicen los partidos" not in page  # sin registro de partidos de Brasil
    assert "Calendario oficial" not in page and "Fecha declarada" in page
