"""Nombramientos y ceses del BOE: sumarios reales (seccion II.A del 7 y 8 de octubre de 2026)."""

import json
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from truthnews.data import nombramientos as nb

FIX = Path(__file__).parent / "fixtures"


def load(day: str) -> dict:
    return json.loads((FIX / f"boe_sumario_{day}_2A.json").read_text())


def test_parse_real_summary_keeps_only_section_2a():
    items = nb.parse(load("20261007"), date(2026, 10, 7))
    assert len(items) == 13 and all(i.fecha == "2026-10-07" for i in items)
    assert all(i.id.startswith("BOE-A-2026-") and i.url.startswith("https://www.boe.es/") for i in items)
    by_person = {i.persona: i for i in items if i.persona}
    gab = by_person["María Tejero Martín"]
    assert gab.tipo == "nombramiento"
    assert gab.cargo == "Directora del Gabinete del Secretario de Estado para la Unión Europea"
    assert gab.departamento.startswith("MINISTERIO")
    # Un ascenso militar: persona si, cargo no (solo se extrae para nombramientos y ceses).
    assert by_person["Francisco Javier Moscoso Sicardo"].tipo == "ascenso"
    assert by_person["Francisco Javier Moscoso Sicardo"].cargo == ""


def test_combined_cese_and_appointment_does_not_leak_into_post():
    items = nb.parse(load("20261008"), date(2026, 10, 8))
    cese = next(i for i in items if i.persona == "Jaime Serrano-Jover González")
    assert cese.tipo == "cese" and cese.cargo.startswith("Fiscal Delegado de la Fiscalía Especial")
    assert "se nombra" not in cese.cargo and cese.cargo.endswith("Santa Cruz de Tenerife")
    fiscal = next(i for i in items if i.persona == "María Dolores Rial de la Calle")
    assert fiscal.cargo == "Teniente Fiscal de la Fiscalía de la Comunidad Autónoma de las Illes Balears"


def test_title_rules():
    t = (
        "Real Decreto 785/2026, por el que se designa Embajador de España en la "
        "República de Angola a don Miguel Utray Delgado."
    )
    assert nb.kind_of("", t) == "nombramiento" and nb.person_of(t) == "Miguel Utray Delgado"
    assert nb.post_of(t, "nombramiento") == "Embajador de España en la República de Angola"
    t = (
        "Orden INT/1091/2026, por la que se nombra para el Mando de la Jefatura "
        "de Policía Marítima (Madrid), "
        "al General de Brigada don José Miguel García Malo de Molina Martínez."
    )
    assert nb.post_of(t, "nombramiento") == "Mando de la Jefatura de Policía Marítima (Madrid)"
    assert nb.person_of(t) == "José Miguel García Malo de Molina Martínez"
    t = (
        "Orden INT/1089/2026, por la que se dispone el cese del Teniente General don Francisco "
        "Javier Moscoso Sicardo en el Mando de la Jefatura."
    )
    assert nb.kind_of("Ceses", t) == "cese" and nb.post_of(t, "cese") == "Mando de la Jefatura"
    t = (
        "Real Decreto 1/2026, por el que se dispone el cese de don Carlos Moreno Blanco "
        "como Secretario General, a petición propia."
    )
    assert nb.kind_of("", t) == "cese" and nb.post_of(t, "cese") == "Secretario General"
    # Nombramientos colectivos: sin persona ni cargo inventados.
    t = (
        "Resolución de 21 de septiembre de 2026, de la Universidad de Almería, por la "
        "que se nombran Catedráticos de Universidad."
    )
    assert nb.person_of(t) == "" and nb.post_of(t, "nombramiento") == ""
    assert nb.kind_of("Promociones", "Resolución sin más") == "otro"
    assert nb.kind_of("Jubilaciones", "x") == "situacion" and nb.kind_of("Destinos", "x") == "destino"


def test_fetch_uses_open_data_api_and_fails_closed():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path.endswith("20261007"):
            return httpx.Response(200, json=load("20261007"))
        return httpx.Response(404)

    t = httpx.MockTransport(handler)
    items = nb.nombramientos(date(2026, 10, 7), transport=t)
    assert len(items) == 13 and seen[0].headers["Accept"] == "application/json"
    assert str(seen[0].url) == "https://www.boe.es/datosabiertos/api/boe/sumario/20261007"
    assert nb.nombramientos(date(2026, 10, 11), transport=t) == []  # sin BOE ese dia
    assert nb.as_dicts(items[:1])[0]["id"] == items[0].id
    assert nb.parse({}, date(2026, 10, 7)) == []


# --- Pagina /nombramientos ----------------------------------------------------------------------------


class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def boe_transport(calls):
    def handler(request):
        calls.append(str(request.url))
        day = request.url.path.rsplit("/", 1)[-1]
        if day in ("20261007", "20261008"):
            return httpx.Response(200, json=load(day))
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_boe_days_caches_past_days_and_retries_empty_ones():
    from truthnews.web.appointments import BoeDays

    calls, clock = [], Clock()
    days = BoeDays(boe_transport(calls), clock)
    today = date(2026, 10, 9)
    assert len(days.day(date(2026, 10, 7), today)) == 13
    days.day(date(2026, 10, 7), today)
    assert len(calls) == 1  # dia pasado con datos: no se vuelve a pedir
    assert days.latest(today) == (date(2026, 10, 8), days.day(date(2026, 10, 8), today))
    n = len(calls)
    days.day(date(2026, 10, 9), today)
    assert len(calls) == n  # vacio reciente: se recuerda 10 min
    clock.now += 601
    days.day(date(2026, 10, 9), today)
    assert len(calls) == n + 1
    assert BoeDays(boe_transport([]), clock).latest(date(2026, 10, 20)) == (date(2026, 10, 20), [])


def test_boe_days_network_error_is_empty():
    from truthnews.web.appointments import BoeDays

    def boom(request):
        raise httpx.ConnectError("caido", request=request)

    assert BoeDays(httpx.MockTransport(boom)).day(date(2026, 10, 7), date(2026, 10, 9)) == []


def test_name_keys():
    from truthnews.web.appointments import _name_keys

    assert _name_keys("María Dolores Rial de la Calle") == ("María", "Rial")
    assert _name_keys("Josu Aranbarri Erkiaga") == ("Josu", "Aranbarri")
    assert _name_keys("Ana Pérez") == ("Ana", "Pérez") and _name_keys("Ana") is None


def test_appointments_page(engine, session):
    from fastapi.testclient import TestClient

    from truthnews.config import Settings
    from truthnews.models import Article, Outlet
    from truthnews.web.app import create_app
    from truthnews.web.appointments import BoeDays

    o = Outlet(slug="m", name="Medio", homepage="https://m.es", country="ES", language="es", scope="nacional")
    session.add(o)
    session.flush()
    for i, title in enumerate(
        [
            "Maria Dolores Rial, nueva teniente fiscal de Baleares",  # sin tilde: se normaliza
            "Rial, el apellido de otra persona",  # mismo apellido, otro nombre: no cuenta
            "María compra material escolar",  # 'rial' dentro de otra palabra: no cuenta
        ]
    ):
        session.add(
            Article(
                outlet_id=o.id,
                url=f"https://m.es/{i}",
                url_hash=f"r{i:063d}",
                title=title,
                published_at=datetime(2026, 10, 8, 9, tzinfo=UTC),
                language="es",
                country="ES",
                category="politica",
                topics=[],
            )
        )
    session.commit()
    calls = []
    tc = TestClient(
        create_app(Settings(database_url="sqlite://"), engine=engine, boe_days=BoeDays(boe_transport(calls)))
    )
    page = tc.get("/nombramientos?fecha=2026-10-08").text
    assert "Nombramientos y ceses" in page and "08/10/2026" in page
    assert "María Dolores Rial de la Calle" in page and "Teniente Fiscal de la Fiscalía" in page
    assert 'href="https://www.boe.es/diario_boe/txt.php?id=BOE-A-' in page and "Día siguiente" in page
    assert "Destinos, ascensos y nombramientos colectivos" in page and ">ceses<" in page
    assert "En los medios (1)" in page and "nueva teniente fiscal de Baleares" in page
    assert "el apellido de otra persona" not in page and "material escolar" not in page
    assert "Ministerio de la Presidencia, Justicia y Relaciones con las Cortes" in page
    assert "fecha=2026-10-07" in page and 'href="/nombramientos"' in page  # pie
    empty = tc.get("/nombramientos?fecha=2026-10-11").text
    assert "no publicó nombramientos" in empty
    assert tc.get("/nombramientos").status_code == 200  # hoy o el ultimo BOE con datos
    for bad in ("2026-13-01", "2999-01-01", "2001-01-01"):
        assert tc.get(f"/nombramientos?fecha={bad}").status_code == 404
    assert "/nombramientos" in tc.get("/sitemaps/paginas-1.xml").text
    assert "Appointments and dismissals" in tc.get("/nombramientos?fecha=2026-10-07&lang=en").text


# --- Confirmacion en el BOE de lo que cuenta una noticia ------------------------------------------------


def warmed_index(window=36500):
    from truthnews.web.appointments import BoeDays, BoeIndex

    days = BoeDays(boe_transport([]))
    for d in (date(2026, 10, 7), date(2026, 10, 8)):
        days.day(d, date(2026, 10, 9))
    index = BoeIndex(days, window, background=False)
    index._warmed_at = index._clock()  # ya caliente: no se descarga nada mas
    return index


def test_confirmations_need_name_and_appointment_wording():
    index = warmed_index()
    today = date(2026, 10, 9)
    hit = index.confirmations(["El Gobierno nombra a Maria Dolores Rial teniente fiscal en Baleares"], today)
    assert [i.persona for i in hit] == ["María Dolores Rial de la Calle"]
    assert index.confirmations(["María Dolores Rial asistió a un acto"], today) == []  # sin verbo de cargo
    assert index.confirmations(["El Gobierno nombra a otra persona"], today) == []
    assert index.confirmations([""], today) == []
    assert warmed_index(window=0).confirmations(["nombra a María Dolores Rial"], today) == []


def test_index_warms_missing_days_once_and_skips_sundays():
    from truthnews.web.appointments import BoeDays, BoeIndex

    calls = []
    index = BoeIndex(BoeDays(boe_transport(calls)), 3, background=False)
    index.ensure_warm(date(2026, 10, 12))  # lunes: 12, 10 y 9 (el 11 es domingo)
    assert sorted(c[-8:] for c in calls) == ["20261009", "20261010", "20261012"]
    index.ensure_warm(date(2026, 10, 12))
    assert len(calls) == 3  # no se repite antes de 6 h
    index.days.warm(date(2026, 10, 9), 2, pause=0)  # el 8 y el 7 tienen datos: se piden una vez y quedan
    index.days.warm(date(2026, 10, 9), 2, pause=0)
    assert sum(c.endswith("20261008") for c in calls) == 1


def test_story_and_article_show_boe_confirmation(engine, session):
    from fastapi.testclient import TestClient

    from truthnews.config import Settings
    from truthnews.models import Article, Outlet
    from truthnews.web.app import create_app

    o = Outlet(slug="m", name="Medio", homepage="https://m.es", country="ES", language="es", scope="nacional")
    session.add(o)
    session.flush()
    a = Article(
        outlet_id=o.id,
        url="https://m.es/n",
        url_hash="n" * 64,
        title="El Gobierno nombra a María Dolores Rial teniente fiscal de Baleares",
        published_at=datetime(2026, 10, 8, 9, tzinfo=UTC),
        language="es",
        country="ES",
        category="politica",
        topics=[],
    )
    session.add(a)
    session.commit()
    tc = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine, boe_index=warmed_index()))
    page = tc.get(f"/noticia/{a.id}?ficha=1", follow_redirects=True).text
    assert "Consta en el BOE" in page and "María Dolores Rial de la Calle" in page
    assert "Teniente Fiscal de la Fiscalía de la Comunidad Autónoma de las Illes Balears" in page
    assert "BOE del 08/10/2026" in page and "diario_boe/txt.php?id=BOE-A-" in page
