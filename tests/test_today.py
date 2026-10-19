"""Hoy en 1 minuto (ADR 0047): claves del dia solo con lo contrastado, pagina, RSS e imagenes."""

import io

from fastapi.testclient import TestClient
from PIL import Image

from tests.test_social import NOW, _story, _verification
from truthnews.config import Settings
from truthnews.social import today
from truthnews.web.app import create_app


def _client(engine):
    return TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))


def test_empty_day_says_so_and_does_not_fill(engine, session):
    assert today.keys(session, NOW) == []
    page = _client(engine).get("/hoy").text
    assert "Hoy todavía no hay nada contrastado con datos oficiales" in page
    from truthnews.web import structured

    assert not structured.of_type(page, "ItemList")  # sin claves no se declara lista
    img = Image.open(io.BytesIO(_client(engine).get("/og/hoy-vertical.png").content))
    assert img.size == (1080, 1350)


def test_keys_order_sources_and_outputs(engine, session):
    st = _story(session, "Desalojo en la calle Mayor", [400, 1000])
    _verification(session, st, verdict="verdadero")
    false = _verification(session, st, verdict="falso")  # mismo indicador: solo sale una vez
    _verification(session, st, verdict="enganoso", with_url=False)  # sin enlace a la fuente: fuera
    other = _story(session, "Otra historia con cifras", [300, 700])
    for s_ in (st, other):
        s_.contrast = {"disputas": ["detenidos"]}  # lo que deja el puntuador (ADR 0012)
    session.commit()
    ks = today.keys(session, NOW)
    assert [k.kind for k in ks] == ["verificacion", "disputa", "disputa"]
    v = ks[0]
    assert v.ref_id == false.claim_id and v.verdict == "falso" and v.official and v.source_url
    assert v.path == f"/verificacion/{false.claim_id}"
    d = next(k for k in ks if k.kind == "disputa" and k.ref_id == other.id)
    assert d.verdict is None and d.official is None and "sin dato oficial" in d.sentence
    assert d.said == "300 – 700"
    assert today.keys(session, NOW, limit=1) == ks[:1]

    client = _client(engine)
    page = client.get("/hoy").text
    assert "Hoy en 1 minuto" in page and v.sentence in page and "Cifras en disputa" in page
    assert 'href="/hoy.xml"' in page and "og/hoy-horizontal.png" in page
    from truthnews.web import structured

    (lst,) = structured.of_type(page, "ItemList")
    urls = [i["url"] for i in lst["itemListElement"]]
    assert lst["numberOfItems"] == len(urls) >= 2 and lst["url"].endswith("/hoy")
    assert any("/verificacion/" in u for u in urls) and any("/historia/" in u for u in urls)
    assert [i["position"] for i in lst["itemListElement"]] == list(range(1, len(urls) + 1))
    (crumbs,) = structured.of_type(page, "BreadcrumbList")
    assert crumbs["itemListElement"][-1]["item"].endswith("/hoy")
    rss = client.get("/hoy.xml")
    assert rss.headers["content-type"].startswith("application/rss+xml") and "Dato oficial" in rss.text
    for fmt, size in (("vertical", (1080, 1350)), ("cuadrada", (1080, 1080)), ("horizontal", (1200, 630))):
        r = client.get(f"/og/hoy-{fmt}.png")
        assert r.status_code == 200 and Image.open(io.BytesIO(r.content)).size == size
    assert client.get("/og/hoy-gigante.png").status_code == 404
    assert "Today in 1 minute" in client.get("/en/hoy").text


def test_today_is_cached_between_crawls(engine, session):
    client = _client(engine)
    assert "Hoy todavía no hay nada contrastado" in client.get("/hoy").text
    st = _story(session, "Desalojo en la calle Mayor", [400, 1000])
    _verification(session, st, verdict="falso")
    session.commit()
    # Dentro de los 5 minutos la pagina no se recalcula (cambia con el ciclo del worker, no por visita).
    assert "Hoy todavía no hay nada contrastado" in client.get("/hoy").text
    assert "Hoy todavía no hay nada contrastado" not in _client(engine).get("/hoy").text
