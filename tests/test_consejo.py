"""Consejo de Ministros frente al BOE: reales decretos anunciados y si constan publicados."""

from datetime import date
from pathlib import Path

import httpx
from fastapi.testclient import TestClient

from truthnews.config import Settings
from truthnews.data import consejo
from truthnews.web import council
from truthnews.web.app import create_app

FIX = Path(__file__).parent / "fixtures"
PAGES = "/consejodeministros/referencias/Paginas/2026"
REF = f"{PAGES}/20261013-referencia-rueda-de-prensa-ministros.aspx"
INDEX_HTML = f"""<a href="{REF}">13</a><a href="{REF}">13 otra vez</a>
<a href="{PAGES}/20261006-referencia-rueda-de-prensa-ministros.aspx">6</a>
<a href="/consejodeministros/referencias/Paginas/index.aspx">indice</a>"""
TODAY = date(2026, 10, 19)
# Titulos reales del BOE del 14/10/2026 (BOE-A-2026-21318 y 21323) y uno de otro dia que no debe casar.
BOE_14 = [
    {
        "id": "BOE-A-2026-21318",
        "titulo": "Real Decreto-ley 30/2026, de 13 de octubre, por el que se aprueban medidas extraordinarias"
        " y urgentes de apoyo financiero a la Ciudad de Ceuta.",
        "url": "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-21318",
    },
    {
        "id": "BOE-A-2026-21323",
        "titulo": "Real Decreto 841/2026, de 13 de octubre, por el que se nombra Subsecretaria de Trabajo y"
        " Economía Social a doña María Concepción Peinado Reillo.",
        "url": "https://www.boe.es/diario_boe/txt.php?id=BOE-A-2026-21323",
    },
    {
        "id": "BOE-A-2026-99999",
        "titulo": "Real Decreto 800/2026, de 6 de octubre, por el que se modifica el Estatuto Orgánico de la"
        " Comisión Nacional de los Mercados y la Competencia.",
        "url": "https://www.boe.es/x",
    },
]


def reference() -> str:
    return (FIX / "moncloa_referencia_20261013.html").read_text()


def test_reference_links_newest_first_without_repeats():
    links = consejo.reference_links(INDEX_HTML)
    assert [d for d, _ in links] == [date(2026, 10, 13), date(2026, 10, 6)]
    assert links[0][1] == consejo.SITE + REF


def test_parse_reference_keeps_royal_decrees_with_their_ministry():
    decs = consejo.parse_reference(reference(), date(2026, 10, 13), "https://m/ref")
    assert [(d.tipo, d.ministerio) for d in decs] == [
        ("real-decreto", "Economía, Comercio y Empresa"),
        ("real-decreto-ley", "Hacienda"),
        ("real-decreto", "Trabajo y Economía Social"),  # acuerdos de personal incluidos
    ]
    assert "Ciudad de Ceuta" in decs[1].texto and "ACUERDO" not in " ".join(d.texto for d in decs)
    assert consejo.parse_reference("<html>sin sumario</html>", date(2026, 10, 13), "u") == []


def test_match_needs_same_kind_date_and_purpose():
    cnmc, ceuta, sub = consejo.parse_reference(reference(), date(2026, 10, 13), "u")
    assert consejo.match(ceuta, BOE_14)["id"] == "BOE-A-2026-21318"
    assert consejo.match(sub, BOE_14)["id"] == "BOE-A-2026-21323"
    assert consejo.match(cnmc, BOE_14) is None  # mismo objeto, pero fechado el 6: otro real decreto
    rdl_as_rd = consejo.Decreto(ceuta.fecha, "", "real-decreto", ceuta.texto, "u")
    assert consejo.match(rdl_as_rd, BOE_14) is None  # un real decreto no casa con un real decreto-ley


def test_status_and_window():
    _, ceuta, _ = consejo.parse_reference(reference(), date(2026, 10, 13), "u")
    assert consejo.status(ceuta, {"id": "x"}, TODAY) == "publicado"
    assert consejo.status(ceuta, None, TODAY) == "pendiente"
    assert consejo.status(ceuta, None, date(2026, 11, 12)) == "no_publicado"
    window = consejo.boe_window(ceuta, TODAY)
    assert window[0] == date(2026, 10, 13) and date(2026, 10, 18) not in window  # domingo


class FakeDays:
    def __init__(self, by_day):
        self.by_day = by_day

    def day(self, d, today):
        return self.by_day.get(d, [{"id": "otro", "titulo": "Orden", "url": "u"}])


def test_compare_groups_by_council_and_never_says_unpublished_without_reading_every_boe():
    decs = consejo.parse_reference(reference(), date(2026, 10, 13), "https://m/ref")
    [c] = council.compare(decs, FakeDays({date(2026, 10, 14): BOE_14}), TODAY)
    assert [r.estado for r in c.rows] == ["pendiente", "publicado", "publicado"]
    assert c.rows[1].boe_fecha == "2026-10-14" and c.rows[1].dias == 1 and c.count("publicado") == 2
    late = date(2026, 11, 20)
    [c] = council.compare(decs, FakeDays({}), late)
    assert {r.estado for r in c.rows} == {"no_publicado"}
    gap = FakeDays({date(2026, 10, 20): []})  # un BOE que no se pudo leer
    [c] = council.compare(decs, gap, late)
    assert {r.estado for r in c.rows} == {"sin_comprobar"}


def transport():
    def handler(req: httpx.Request) -> httpx.Response:
        if req.url.host == "www.boe.es":
            if req.url.path.endswith("20261016"):
                return httpx.Response(200, text="<html>mantenimiento</html>")  # no es JSON
            data = [{"identificador": "BOE-A-1", "titulo": "Orden"}]
            if req.url.path.endswith("20261014"):
                data = [
                    {"identificador": i["id"], "titulo": i["titulo"], "url_html": i["url"]} for i in BOE_14
                ]
            return httpx.Response(200, json={"data": {"sumario": {"items": data}}})
        if req.url.path.endswith("index.aspx"):
            return httpx.Response(200, text=INDEX_HTML)
        if "20261013" in req.url.path:
            return httpx.Response(200, text=reference())
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_page_shows_both_citations(engine):
    index = council.CouncilIndex(transport=transport(), background=False)
    assert index.councils(TODAY)[0].count("publicado") == 2
    app = create_app(Settings(database_url=str(engine.url)), engine=engine, council_index=index)
    html = TestClient(app).get("/consejo-de-ministros").text
    assert "BOE-A-2026-21318" in html and "Publicado en el BOE el 14/10 (1 día después)" in html
    assert "Pendiente de publicación en el BOE (6 días; el aviso llega a los 30)" in html
    assert consejo.SITE + REF in html


def test_page_while_loading_and_when_moncloa_fails(engine):
    def down(req):
        raise httpx.ConnectError("caido")

    index = council.CouncilIndex(transport=httpx.MockTransport(down), background=False)
    assert index.councils(TODAY) is None
    app = create_app(Settings(database_url=str(engine.url)), engine=engine, council_index=index)
    assert "Vuelve en un minuto" in TestClient(app).get("/consejo-de-ministros").text


def test_purpose_without_por_el_que():
    """Real caso del 5/10/2026: el real decreto de disolucion no dice "por el que"."""
    dec = consejo.Decreto(
        "2026-10-05",
        "Presidencia",
        "real-decreto",
        "REAL DECRETO de disolución del Congreso de los Diputados y del Senado y de convocatoria de"
        " elecciones.",
        "u",
    )
    boe_item = {
        "id": "BOE-A-2026-20742",
        "titulo": "Real Decreto 806/2026, de 5 de octubre, de disolución del Congreso de los Diputados y del"
        " Senado y de convocatoria de elecciones.",
    }
    assert consejo.match(dec, [boe_item])["id"] == "BOE-A-2026-20742"
