"""Programas electorales y promesas (ADR 0037): descubrimiento, importacion, promesas y paginas."""

import hashlib
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from truthnews.config import Settings
from truthnews.elections import calendar as cal
from truthnews.elections import programs as pg
from truthnews.models import PoliticalStatement, Program, Promise
from truthnews.registry import ActorSpec
from truthnews.web.app import create_app

BNG = ActorSpec("bng", "BNG", "Bloque Nacionalista Galego", "https://www.bng.gal", "ES")


def make_pdf(pages: list[str]) -> bytes:
    """PDF minimo valido con una linea de texto por pagina (Helvetica)."""
    font = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    objs = ["<< /Type /Catalog /Pages 2 0 R >>", None, font]
    kids = []
    for text in pages:
        safe = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream = f"BT /F1 10 Tf 40 760 Td ({safe}) Tj ET".encode("latin-1")
        objs.append(f"<< /Length {len(stream)} >>\nstream\n{stream.decode('latin-1')}\nendstream")
        content = len(objs)
        objs.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content} 0 R "
            "/Resources << /Font << /F1 3 0 R >> >> >>"
        )
        kids.append(f"{len(objs)} 0 R")
    objs[1] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = b"%PDF-1.4\n", []
    for i, body in enumerate(objs, 1):
        offsets.append(len(out))
        out += f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{o:010d} 00000 n \n".encode() for o in offsets)
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return out


PDF = make_pdf(
    [
        "Bajaremos el IVA de los alimentos basicos y de la luz durante toda la legislatura.",
        "Queremos un pais mejor para todas las personas que viven en el.",
        "Construiremos 100.000 viviendas publicas en alquiler asequible en cuatro anos.",
    ]
)


def test_election_of_reads_kind_and_year_from_real_links():
    assert pg.election_of("https://www.bng.gal/media/files/2023/07/05/23_bng_xerais_programa.pdf", "PDF") == (
        "generales",
        2023,
    )
    url = "https://coalicioncanaria.org/x/02 Programa Electoral Elecciones Generales 2019.pdf"
    assert pg.election_of(url, "02 Programa Electoral Elecciones Generales 2019") == ("generales", 2019)
    assert pg.election_of("https://m.es/Un-Programa-para-ti.pdf", "Descarga el programa 23J") == (
        "generales",
        2023,
    )
    assert pg.election_of("https://b.gal/2020/programa_galegas_2020.pdf", "Galegas") == ("autonomicas", 2020)
    assert pg.election_of("https://b.gal/Programa_Europeas_2009.pdf", "Europeas") == ("europeas", 2009)
    assert pg.election_of("https://x.es/memoria-2023.pdf", "Memoria anual") is None  # sin tipo
    assert pg.election_of("https://x.es/programa-generales.pdf", "Programa") is None  # sin ano


def test_links_and_pages_from_party_html():
    home = (
        '<a href="/estaticas/programas-eleitorais.html">Programas eleitorais</a>'
        '<a href="https://otro.example/programa">Programa ajeno</a>'
        '<a href="/media/2023/07/05/23_bng_xerais_programa.pdf">Programa xerais</a>'
        '<a href="/media/informe-2023.pdf">Informe de xestion 2023</a>'
    )
    assert pg.program_pages(BNG, home, "https://www.bng.gal/") == [
        "https://www.bng.gal/estaticas/programas-eleitorais.html"
    ]
    found = pg.program_links(BNG, "https://www.bng.gal/", home, program_page=False)
    assert [c.url for c in found] == ["https://www.bng.gal/media/2023/07/05/23_bng_xerais_programa.pdf"]
    # En una pagina de programas cuenta cualquier PDF con tipo y ano, aunque el enlace diga solo "PDF".
    page = '<a href="/m/2019/04/26/bng_europeas_programa.pdf">PDF</a><a href="/m/logo.png">x</a>'
    found = pg.program_links(BNG, "https://www.bng.gal/p.html", page, program_page=True)
    assert [(c.election_kind, c.election_year, c.title) for c in found] == [
        ("europeas", 2019, "bng europeas programa")
    ]


def test_promises_are_commitments_quoted_with_their_page():
    pages = [
        "Estableceremos como objetivo central de la política económica que la tasa de paro converja con "
        "la media europea.\nQueremos un país con futuro para toda la gente joven y sus familias.",
        "Reordenaremos el tiempo de trabajo, incluyendo la reducción de la jornada laboral sin reducción "
        "de salario. Para ello hace falta una mayoría amplia en las Cortes Generales del país.",
        "O BNG defenderá a transferencia da AP-9 e o seu traspaso á Xunta de Galiza sen custo.",
        "Para ello, en esta legislatura llevaremos a cabo las siguientes medidas concretas:",
        "Reordenaremos el tiempo de trabajo, incluyendo la reducción de la jornada laboral sin reducción "
        "de salario.",
    ]
    found = pg.promises_in(pages, names=("bng",))
    assert [p for p, _ in found] == [1, 2, 3]  # el repetido de la pagina 4 no vuelve a entrar
    assert found[0][1].startswith("Estableceremos") and "Queremos" not in " ".join(t for _, t in found)
    assert pg.promises_in(pages[2:3]) == []  # tercera persona sin nombrar al partido: no
    assert pg.topic_of(found[1][1]) == "empleo" and pg.topic_of("Una frase sin tema claro.") is None
    assert pg.party_names("bng") == ("bng", "bloque nacionalista galego")


def _routes(calls):
    home = (
        '<html>' + "x" * 1200 + '<a href="/programas.html">Programas electorales</a></html>'
    )
    page = '<a href="/f/2023/programa-generales-2023.pdf">Programa electoral generales 2023</a>'

    def handler(request):
        calls.append(str(request.url))
        path = request.url.path
        if path == "/robots.txt":
            return httpx.Response(200, text="User-agent: *\nDisallow: /privado/\n")
        if path == "/":
            return httpx.Response(200, text=home)
        if path == "/programas.html":
            return httpx.Response(200, text=page)
        if path.endswith(".pdf"):
            return httpx.Response(200, content=PDF)
        return httpx.Response(404)

    return httpx.MockTransport(handler)


def test_run_discovers_imports_and_extracts(session):
    calls = []
    actor = ActorSpec("sumar", "Sumar", "Movimiento Sumar", "https://partido.example", "ES")
    blocked = ActorSpec("vox", "Vox", "Vox", "https://bloqueado.example", "ES")

    def handler(request):
        if request.url.host == "bloqueado.example" and request.url.path != "/robots.txt":
            return httpx.Response(403, text="no")
        return _routes(calls).handle_request(request)

    clock = iter(range(0, 10**6, 100))
    out = pg.run(
        session,
        Settings(database_url="sqlite://"),
        clock=lambda: next(clock),
        transport=httpx.MockTransport(handler),
        actors=[actor, blocked],
    )
    session.commit()
    assert out["new_programs"] == 1 and out["imported"] == 1
    assert out["unread"] == {"vox": "la portada responde 403 (2 bytes)"}
    prog = session.scalars(select(Program)).one()
    got = (prog.actor, prog.election_kind, prog.election_year, prog.status)
    assert got == ("sumar", "generales", 2023, "importado")
    assert prog.n_pages == 3 and prog.content_sha256 == hashlib.sha256(PDF).hexdigest()
    assert prog.found_on == "https://partido.example/programas.html"
    promises = session.scalars(select(Promise).order_by(Promise.page)).all()
    assert [(p.page, p.topic) for p in promises] == [(1, "impuestos"), (3, "vivienda")]
    assert all(p.program_id == prog.id and p.election_year == 2023 for p in promises)
    # Segunda pasada en las 6 h siguientes: ni se vuelve a descubrir ni se duplica nada.
    pg._last_discovery.clear()
    n = len(calls)
    pg.run(
        session,
        Settings(database_url="sqlite://"),
        clock=lambda: 0,
        transport=httpx.MockTransport(handler),
        actors=[actor],
    )
    session.commit()
    assert session.scalar(select(Program.id).where(Program.id != prog.id)) is None
    assert len(session.scalars(select(Promise)).all()) == 2 and len(calls) > n


@pytest.mark.parametrize(
    "response, status",
    [
        (httpx.Response(200, content=b"<html>no</html>"), "error"),
        (httpx.Response(500), "error"),
        (httpx.Response(200, content=b"%PDF-1.4 roto"), "error"),
    ],
)
def test_import_failures_keep_the_link(session, response, status):
    prog = Program(
        actor="pp", country="ES", election_kind="generales", election_year=2026, title="t",
        url="https://p.example/x.pdf", url_hash="h", found_on="https://p.example/",
    )
    session.add(prog)
    session.flush()

    async def go():
        transport = httpx.MockTransport(
            lambda r: httpx.Response(404) if r.url.path == "/robots.txt" else response
        )
        async with pg.PoliteClient("t", per_domain_delay=0, transport=transport) as c:
            return await pg.import_one(c, session, prog, datetime.now(UTC))

    import asyncio

    assert asyncio.run(go()) == status and prog.note and prog.text is None


def test_robots_blocked_programme_is_linked_not_downloaded(session):
    prog = Program(
        actor="pp", country="ES", election_kind="generales", election_year=2026, title="t",
        url="https://p.example/privado/x.pdf", url_hash="h2", found_on="https://p.example/",
    )
    session.add(prog)
    session.flush()

    async def go():
        transport = httpx.MockTransport(
            lambda r: httpx.Response(200, text="User-agent: *\nDisallow: /privado/\n")
            if r.url.path == "/robots.txt"
            else httpx.Response(200, content=PDF)
        )
        async with pg.PoliteClient("t", per_domain_delay=0, transport=transport) as c:
            return await pg.import_one(c, session, prog, datetime.now(UTC))

    import asyncio

    assert asyncio.run(go()) == "bloqueado" and prog.text is None


def _statement(session, actor, text, when):
    url = f"https://{actor}.example/{hashlib.md5(text.encode()).hexdigest()}"
    st = PoliticalStatement(
        actor=actor, country="ES", channel="web", url=url, url_hash=hashlib.sha256(url.encode()).hexdigest(),
        text=text, published_at=when,
    )
    session.add(st)
    session.flush()
    return st


def test_statement_promises_and_one_source_constraint(session):
    now = datetime.now(UTC)
    _statement(session, "pp", "Bajaremos el IRPF a las rentas medias y suprimiremos patrimonio.", now)
    _statement(session, "pp", "Hoy hemos visitado una fabrica en Valladolid con trabajadores.", now)
    old = now - timedelta(days=90)
    _statement(session, "pp", "Bajaremos el IRPF antes de la convocatoria: no cuenta.", old)
    assert pg.statement_promises(session, now - timedelta(days=30), "ES") == 1
    assert pg.statement_promises(session, now - timedelta(days=30), "ES") == 0  # sin duplicados
    p = session.scalars(select(Promise)).one()
    assert p.statement_id and p.program_id is None and p.topic == "impuestos"
    session.add(Promise(actor="pp", country="ES", text="x", text_hash="z", made_at=now))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_election_page_shows_programmes_and_promises(engine, session):
    now = datetime.now(UTC)
    today = now.date()
    poll = today + timedelta(days=20)
    reg = {
        "elections": [
            {
                "country": "ES", "kind": "generales", "date": poll.isoformat(),
                "convened": (today - timedelta(days=10)).isoformat(),
                "source": {"label": "Decreto", "url": "https://www.boe.es/x"},
            }
        ]
    }
    old = Program(
        actor="sumar", country="ES", election_kind="generales", election_year=poll.year - 3,
        title="Un programa para ti", url="https://s.example/old.pdf", url_hash="o", found_on="https://s.example/",
        status="importado", n_pages=182,
    )
    new = Program(
        actor="sumar", country="ES", election_kind="generales", election_year=poll.year,
        title="Programa nuevo", url="https://s.example/new.pdf", url_hash="n", found_on="https://s.example/",
        status="importado", n_pages=90,
    )
    session.add_all([old, new])
    session.flush()
    session.add_all(
        [
            Promise(program_id=old.id, actor="sumar", country="ES", election_kind="generales",
                    election_year=poll.year - 3, text="Reduciremos la jornada laboral a 37,5 horas.",
                    text_hash="a", page=7, topic="empleo", made_at=now - timedelta(days=1000)),
            Promise(program_id=new.id, actor="sumar", country="ES", election_kind="generales",
                    election_year=poll.year, text="Construiremos vivienda publica en alquiler.",
                    text_hash="b", page=12, topic="vivienda", made_at=now - timedelta(days=5)),
        ]
    )
    st = _statement(session, "pp", "Bajaremos el IRPF a las rentas medias ya.", now - timedelta(days=1))
    session.add(Promise(statement_id=st.id, actor="pp", country="ES", text=st.text, text_hash="c",
                        topic="impuestos", made_at=st.published_at))
    session.commit()
    slug = f"es-generales-{poll.isoformat()}"
    client = TestClient(
        create_app(
            Settings(database_url="sqlite://"), engine=engine, elections=cal.Calendar(0, registry_raw=reg)
        )
    )
    page = client.get(f"/elecciones/{slug}").text
    assert "Programa nuevo" in page and "90 páginas" in page
    assert "Construiremos vivienda publica" in page and "#page=12" in page
    assert "Bajaremos el IRPF" in page
    assert f"Lo que prometió en {poll.year - 3}" in page and f"anio={poll.year - 3}" in page
    assert "Reduciremos la jornada" not in page  # lo de la eleccion anterior va en su listado

    r = client.get(f"/elecciones/{slug}/promesas")
    assert r.status_code == 200 and "Construiremos vivienda" in r.text and "Bajaremos el IRPF" in r.text
    assert "Reduciremos la jornada" not in r.text
    r = client.get(f"/elecciones/{slug}/promesas?partido=sumar&anio={poll.year - 3}")
    assert "Reduciremos la jornada" in r.text and "Construiremos vivienda" not in r.text
    assert "noindex" in r.text
    assert "Comparar sus dos últimos programas" in page
    r = client.get(f"/elecciones/{slug}/promesas?partido=sumar")
    assert f"Qué cambia entre su programa de {poll.year - 3} y el de {poll.year}" in r.text
    r = client.get(f"/elecciones/{slug}/promesas?tema=impuestos")
    assert "Bajaremos el IRPF" in r.text and "Construiremos" not in r.text
    assert client.get(f"/elecciones/{slug}/promesas?partido=nadie").status_code == 404
    assert client.get("/elecciones/es-generales-1999-01-01/promesas").status_code == 404
    assert client.get(f"/en/elecciones/{slug}/promesas").status_code == 200


def test_programs_by_actor_prefers_imported_and_latest(session):
    e = cal.Election("ES", "generales", date(2026, 11, 29), "x", "convocada", (cal.Source("d", "u"),))
    for i, (year, status) in enumerate([(2023, "error"), (2023, "importado"), (2019, "importado")]):
        session.add(Program(actor="bng", country="ES", election_kind="generales", election_year=year,
                            title=f"p{i}", url=f"u{i}", url_hash=f"h{i}", found_on="f", status=status))
    session.flush()
    from truthnews.elections import views

    cur, prev = views.programs_by_actor(session, e, ["bng"])["bng"]
    assert cur is None and prev.title == "p1"


def test_compare_programmes_pairs_conservatively():
    from types import SimpleNamespace as N

    from truthnews.elections import changes

    before = [
        N(id=1, text="Reclamaremos una mayor participación de las empresas canarias en los programas."),
        N(id=2, text="Crearemos un fondo para rehabilitar viviendas vacías en los municipios rurales."),
        N(id=3, text="Corto."),
    ]
    after = [
        N(
            id=11,
            text="Reclamaremos, por otro lado, una mayor participación de las empresas canarias "
            "en los programas.",
        ),
        N(id=12, text="Bajaremos las tasas aeroportuarias para los residentes en las islas no capitalinas."),
    ]
    c = changes.compare(before, after)
    assert [(a.id, b.id) for a, b, _ in c.repeated] == [(1, 11)] and c.repeated[0][2] >= 0.6
    assert [p.id for p in c.new] == [12] and [p.id for p in c.dropped] == [2]  # la frase corta no cuenta
