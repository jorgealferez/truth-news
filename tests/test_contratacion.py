"""Contratacion publica: BOE seccion V.A (sumario real del 16/10/2026) y adjudicaciones reales de TED."""

import json
import time
from datetime import UTC, date, datetime
from pathlib import Path

import httpx

from truthnews.data import contratacion as ct
from truthnews.web import contracts as cw

FIX = Path(__file__).parent / "fixtures"


def boe_payload() -> dict:
    return json.loads((FIX / "boe_sumario_20261016_5A.json").read_text())


def ted_payload() -> dict:
    return json.loads((FIX / "ted_adjudicaciones_es.json").read_text())


def test_parse_boe_section_5a():
    items = ct.parse_boe(boe_payload(), date(2026, 10, 16))
    assert len(items) == 58
    kinds = {i.tipo for i in items}
    assert kinds == {"formalizacion", "licitacion"}
    assert all(i.organo and i.objeto and i.expediente for i in items)
    assert all(i.id.startswith("BOE-B-2026-") and i.url.startswith("https://www.boe.es/") for i in items)
    jard = next(i for i in items if i.id == "BOE-B-2026-33553")
    assert jard.tipo == "licitacion" and jard.organo == "Dirección del Centro de Estudios Jurídicos, O.A."
    assert jard.objeto.startswith("Mantenimiento de jardinería") and jard.expediente == "2026/CT011SG"


def test_title_rules():
    t = (
        "Anuncio de formalización de contratos de: Ayuntamiento de Xàtiva. Objeto: Limpieza viaria. "
        "Expediente: 12/2026."
    )
    assert ct.kind_of(t) == "formalizacion"
    assert ct.split_title(t) == ("Ayuntamiento de Xàtiva", "Limpieza viaria", "12/2026")
    assert ct.kind_of("Anuncio previo de licitación de: A. Objeto: B.") == "licitacion"
    assert ct.kind_of("Anuncio de corrección de errores de: A. Objeto: B.") == "rectificacion"
    assert ct.kind_of("Resolución de algo") == "otro" and ct.split_title("Resolución de algo") == ("", "", "")


def test_parse_ted_awards():
    items = {a.id: a for a in ct.parse_ted(ted_payload())}
    assert len(items) == 21
    solred = items["691633-2026"]
    assert solred.adjudicatarios == [("Solred, S.A.", "A79707345")] and solred.importe == 330578.51
    assert solred.url == "https://ted.europa.eu/es/notice/-/detail/691633-2026"
    assert solred.objeto.startswith("Contrato Basado En El Acuerdo Marco 21/2023")
    assert "–" not in solred.objeto
    assert solred.fecha.startswith("2026-10")
    # Varios adjudicatarios: TED no da los NIF en el orden de los nombres, asi que no se atribuyen.
    lots = items["692450-2026"]
    assert len(lots.adjudicatarios) == 5 and all(nif == "" for _, nif in lots.adjudicatarios)
    assert len(items["691729-2026"].adjudicatarios) == 8  # nombres repetidos por lote, sin duplicar
    # Identificador que no es un NIF (UTE con dos NIF unidos): se deja vacio.
    assert items["691857-2026"].adjudicatarios == [("UTE ECSA-TECMO", "")]
    assert items["692026-2026"].adjudicatarios == [] and items["692026-2026"].importe is None


def test_natural_persons_are_counted_not_named():
    payload = {
        "notices": [
            {
                "publication-number": "1-2026",
                "winner-name": {"spa": ["JOSE PEREZ GARCIA"]},
                "winner-identifier": ["12345678Z"],
            },
            {
                "publication-number": "2-2026",
                "winner-name": {
                    "spa": ["Ana Ruiz Gil", "Obras Norte, S.L.", "FORMACIO I TREBALL, FUND. PRIV."]
                },
            },
        ]
    }
    a, b = ct.parse_ted(payload)
    assert a.adjudicatarios == [] and a.personas_fisicas == 1
    assert [n for n, _ in b.adjudicatarios] == ["Obras Norte, S.L.", "FORMACIO I TREBALL, FUND. PRIV."]
    assert b.personas_fisicas == 1
    assert ct.is_legal_person("Quien Sea", "B12345674") and not ct.is_legal_person("Obras, S.L.", "X1234567L")
    v = cw.ted_view([a, b])
    assert all("PEREZ" not in f["nombre"] and "Ruiz" not in f["nombre"] for f in v["firms"])


def test_ted_fetch_paginates_and_fails_closed():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        calls.append(body)
        assert request.url == ct.TED_SEARCH and "buyer-country=ESP" in body["query"]
        assert "publication-date>=20261005" in body["query"] and "publication-date<=20261018" in body["query"]
        if body["page"] == 3:
            return httpx.Response(500)
        return httpx.Response(200, json={**ted_payload(), "totalNoticeCount": 1000})

    out = ct.ted_adjudicaciones(date(2026, 10, 5), date(2026, 10, 18), transport=httpx.MockTransport(handler))
    assert [c["page"] for c in calls] == [1, 2, 3] and len(out) == 42


def test_boe_fetch_needs_200():
    t = httpx.MockTransport(lambda r: httpx.Response(404))
    assert ct.boe_anuncios(date(2026, 10, 18), transport=t) == []


def test_core_name_and_searchable():
    assert cw.core_name("ALMIRALL, S.A") == "almirall"
    assert cw.core_name("Técnicos Asociados Informática, Sau") == "tecnicos asociados informatica"
    assert cw.core_name("ZIMMER BIOMET SPAIN, S.L.U.") == "zimmer biomet spain"
    assert cw.searchable("almirall") and cw.searchable("zimmer biomet spain")
    assert not cw.searchable("ute ecsa-tecmo") and not cw.searchable("u.t.e. syneox rail")
    # 'Canon': una sola palabra corta (y comun en castellano) no basta; 'Solred' si.
    assert not cw.searchable("grupo servicios") and not cw.searchable("canon espana")
    assert cw.searchable("solred")


def test_ted_view_does_not_inflate_lots():
    v = cw.ted_view(ct.parse_ted(ted_payload()))
    assert v["total"] == 21 and v["with_amount"] == 19
    zimmer = next(f for f in v["firms"] + v["repeat"] if f["nombre"].startswith("ZIMMER"))
    # Zimmer gana dos avisos con lotes (con y sin coma en el nombre): una sola empresa, sin importe sumado.
    assert len(zimmer["contratos"]) == 2 and zimmer["importe"] == 0 and zimmer["lotes"] == 2
    assert v["largest"][0].id == "691857-2026"
    assert v["firms"][0]["importe"] >= v["firms"][1]["importe"]


def test_caches():
    clock = [0.0]
    calls = []

    def fetch(since, until):
        calls.append((since, until))
        return [] if len(calls) == 1 else ct.parse_ted(ted_payload())

    awards = cw.TedAwards(fetch, clock=lambda: clock[0], background=False)
    assert awards.get(date(2026, 10, 19)) is None
    assert awards.get(date(2026, 10, 19)) is None and len(calls) == 1  # reintento a los 10 min
    clock[0] += cw.RETRY_SECONDS + 1
    since, until, items = awards.get(date(2026, 10, 19))
    assert (since, until) == (date(2026, 10, 5), date(2026, 10, 19)) and len(items) == 21
    clock[0] += cw.RETRY_SECONDS + 1
    assert awards.get(date(2026, 10, 19))[2] is items and len(calls) == 2  # fresco durante 6 h

    def boom(request):
        raise httpx.ConnectError("x")

    # En segundo plano: la primera llamada no espera y devuelve lo que haya (nada); el hilo lo rellena.
    import threading

    done = threading.Event()

    def slow(since, until):
        done.set()
        return ct.parse_ted(ted_payload())

    bg = cw.TedAwards(slow)
    assert bg.get(date(2026, 10, 19)) is None
    assert done.wait(5)
    for _ in range(100):
        if bg.get(date(2026, 10, 19)):
            break
        time.sleep(0.01)
    assert len(bg.get(date(2026, 10, 19))[2]) == 21

    days = cw.BoeContractDays(httpx.MockTransport(boom))
    assert days.day(date(2026, 10, 16), date(2026, 10, 19)) == []


def boe_transport(calls):
    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
        if request.url.path.endswith("/20261016"):
            return httpx.Response(200, json=boe_payload())
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_contracts_page(engine, session):
    from fastapi.testclient import TestClient

    from truthnews.config import Settings
    from truthnews.models import Article, Outlet
    from truthnews.web.app import create_app

    o = Outlet(slug="m", name="Medio", homepage="https://m.es", country="ES", language="es", scope="nacional")
    session.add(o)
    session.flush()
    now = datetime.now(UTC)
    for i, title in enumerate(
        [
            "Moderna Biotech Spain amplia su planta",  # la empresa, sin forma juridica: cuenta
            "La biotecnologia moderna en Espana",  # palabras sueltas: no cuenta
        ]
    ):
        session.add(
            Article(
                outlet_id=o.id,
                url=f"https://m.es/{i}",
                url_hash=f"c{i:063d}",
                title=title,
                published_at=now,
                language="es",
                country="ES",
                category="economia",
                topics=[],
            )
        )
    session.commit()
    calls = []
    tc = TestClient(
        create_app(
            Settings(database_url="sqlite://"),
            engine=engine,
            boe_contracts=cw.BoeContractDays(boe_transport(calls)),
            ted_awards=cw.TedAwards(lambda since, until: ct.parse_ted(ted_payload()), background=False),
        )
    )
    page = tc.get("/contratos?fecha=2026-10-16").text
    assert "Contratos públicos" in page and "16/10/2026" in page
    assert "Mantenimiento de jardinería" in page and "Expediente 2026/CT011SG" in page
    assert 'href="https://www.boe.es/diario_boe/txt.php?id=BOE-B-2026-33553"' in page
    assert "Ministerio de Defensa" in page and ">Formalización<" in page
    assert "Empresas que más suman" in page and "NIF B88625314" in page
    assert 'href="https://ted.europa.eu/es/notice/-/detail/691857-2026"' in page
    assert "En los medios (1)" in page and "amplia su planta" in page and "biotecnologia moderna" not in page
    assert "no implica relación con el contrato" in page
    assert "no publicó anuncios de contratación" in tc.get("/contratos?fecha=2026-10-17").text
    assert tc.get("/contratos").status_code == 200
    for bad in ("2026-13-01", "2999-01-01", "2001-01-01"):
        assert tc.get(f"/contratos?fecha={bad}").status_code == 404
    assert "/contratos" in tc.get("/sitemaps/paginas-1.xml").text
    assert 'href="/contratos"' in page  # pie
    en = tc.get("/contratos?fecha=2026-10-16&lang=en").text
    assert "Public contracts" in en and "Largest contracts" in en

    unavailable = TestClient(
        create_app(
            Settings(database_url="sqlite://"),
            engine=engine,
            boe_contracts=cw.BoeContractDays(boe_transport([])),
            ted_awards=cw.TedAwards(lambda since, until: [], background=False),
        )
    )
    assert "no están disponibles ahora mismo" in unavailable.get("/contratos?fecha=2026-10-16").text


def test_cited_firms_match_full_name_only():
    awards = cw.TedAwards(lambda since, until: ct.parse_ted(ted_payload()), background=False)
    cited = cw.CitedFirms(awards)
    today = date(2026, 10, 19)
    hits = cited.in_texts(["Moderna Biotech Spain amplía su planta en Madrid"], today)
    assert [h["nombre"] for h in hits] == ["MODERNA BIOTECH SPAIN, S.L."]
    assert hits[0]["n"] == 1 and hits[0]["importe"] == 533432
    assert hits[0]["contratos"][0].url.endswith("692013-2026")
    assert cited.in_texts(["La biotecnología moderna en España"], today) == []
    assert cited.in_texts(["La UTE ECSA-TECMO gana"], today) == []  # las UTE no se buscan
    # Una empresa que gana un aviso con lotes: no se da importe (no es solo suyo).
    zimmer = cited.in_texts(["Zimmer Biomet Spain presenta resultados"], today)
    assert zimmer[0]["n"] == 2 and zimmer[0]["importe"] is None
    assert cw.CitedFirms(cw.TedAwards(lambda s, u: [], background=False)).in_texts(["x"], today) == []


def test_article_page_shows_cited_contracts(engine, session):
    from fastapi.testclient import TestClient

    from truthnews.config import Settings
    from truthnews.models import Article, Outlet
    from truthnews.web.app import create_app

    o = Outlet(slug="m", name="Medio", homepage="https://m.es", country="ES", language="es", scope="nacional")
    session.add(o)
    session.flush()
    a = Article(
        outlet_id=o.id,
        url="https://m.es/moderna",
        url_hash="d" * 64,
        title="Moderna Biotech Spain amplía su planta",
        published_at=datetime.now(UTC),
        language="es",
        country="ES",
        category="economia",
        topics=[],
    )
    session.add(a)
    session.commit()
    tc = TestClient(
        create_app(
            Settings(database_url="sqlite://"),
            engine=engine,
            ted_awards=cw.TedAwards(lambda since, until: ct.parse_ted(ted_payload()), background=False),
        )
    )
    page = tc.get(f"/noticia/{a.id}").text
    assert "Contratos públicos de empresas citadas" in page and "MODERNA BIOTECH SPAIN" in page
    assert 'href="https://ted.europa.eu/es/notice/-/detail/692013-2026"' in page
    assert "no implica relación entre la noticia y el contrato" in page
