import httpx
import pytest

from truthnews.crawler import targeted
from truthnews.crawler.targeted import Justification, NotJustified, consult

UA = "truth-news-datos/0.1 (+https://github.com/jorgealferez/truth-news)"
OK = Justification(
    claim="El ayuntamiento dice que gasto 2,1 millones en el contrato X",
    condition="dudas_entre_medios",
    reason="Dos medios dan cifras distintas y el contrato solo esta en el portal de transparencia",
    alternatives_tried=("API de datos abiertos del ayuntamiento: no publica contratos",),
)
BASE = "https://transparencia.ejemplo.es"


def site(routes: dict, seen: list):
    def handler(request: httpx.Request):
        seen.append(str(request.url))
        assert request.headers["user-agent"] == UA  # siempre el agente honesto
        return routes.get(str(request.url), httpx.Response(404))

    return httpx.MockTransport(handler)


def test_needs_full_justification():
    seen = []
    t = site({}, seen)
    for bad in (
        Justification("", "dudas_entre_medios", "x", ("y",)),
        Justification("a", "porque si", "x", ("y",)),
        Justification("a", "falta_pruebas_entidad", "x", ()),
        Justification("a", "falta_pruebas_entidad", "x", ("  ",)),
    ):
        with pytest.raises(NotJustified):
            consult([BASE + "/doc"], bad, UA, transport=t)
    with pytest.raises(NotJustified):
        consult([f"{BASE}/{i}" for i in range(targeted.MAX_PAGES + 1)], OK, UA, transport=t)
    with pytest.raises(NotJustified):
        consult([BASE + "/a", "https://otro.es/b"], OK, UA, transport=t)
    assert seen == []  # sin justificacion no sale ni una peticion


def test_gets_the_document_and_records_everything_even_if_robots_excludes_it():
    seen = []
    routes = {
        BASE + "/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /"),
        BASE + "/contratos": httpx.Response(200, text="<a href='/contratos/x.pdf'>X</a>"),
        BASE + "/contratos/x.pdf": httpx.Response(200, text="Importe: 2.100.000 euros"),
    }
    c = consult([BASE + "/contratos", BASE + "/contratos/x.pdf"], OK, UA, transport=site(routes, seen))
    assert c.outcome == "obtenido" and "2.100.000" in c.document
    assert [v.url for v in c.visits] == [BASE + "/contratos", BASE + "/contratos/x.pdf"]
    assert all(v.robots_excluded and len(v.sha256) == 64 for v in c.visits)
    assert seen == [BASE + "/robots.txt", BASE + "/contratos", BASE + "/contratos/x.pdf"]  # ni una mas
    p = c.evidence_payload()
    assert p["afirmacion"] == OK.claim and p["resultado"] == "obtenido" and len(p["urls"]) == 2
    assert "document" not in p


@pytest.mark.parametrize("status", [401, 403, 429, 451])
def test_stops_at_technical_blocks(status):
    seen = []
    routes = {BASE + "/a": httpx.Response(status), BASE + "/b": httpx.Response(200, text="doc")}
    c = consult([BASE + "/a", BASE + "/b"], OK, UA, transport=site(routes, seen))
    assert c.outcome == "bloqueado" and c.document is None and "bloqueo" in c.visits[-1].note
    assert BASE + "/b" not in seen


def test_stops_at_bot_challenges_errors_and_foreign_redirects():
    seen = []
    challenge = {BASE + "/a": httpx.Response(200, text="<div id='cf-chl-widget'>Verify</div>")}
    assert consult([BASE + "/a"], OK, UA, transport=site(challenge, seen)).outcome == "bloqueado"
    gone = consult([BASE + "/a"], OK, UA, transport=site({}, seen))
    assert gone.outcome == "error" and gone.visits[-1].status == 404
    hop = {
        BASE + "/a": httpx.Response(302, headers={"location": "/b"}),
        BASE + "/b": httpx.Response(200, text="doc"),
    }
    ok = consult([BASE + "/a"], OK, UA, transport=site(hop, seen))
    assert ok.outcome == "obtenido" and [v.note for v in ok.visits] == ["redireccion", ""]
    away = {BASE + "/a": httpx.Response(302, headers={"location": "https://cdn.otro.es/b"})}
    out = consult([BASE + "/a"], OK, UA, transport=site(away, seen))
    assert out.outcome == "bloqueado" and "otro host" in out.visits[-1].note
    assert "https://cdn.otro.es/b" not in seen


def test_network_error_is_recorded():
    def boom(request):
        raise httpx.ConnectError("caido")

    c = consult([BASE + "/a"], OK, UA, transport=httpx.MockTransport(boom))
    assert c.outcome == "error" and "caido" in c.visits[0].note and c.visits[0].robots_excluded is False


def test_crawler_does_not_import_the_exception():
    import pathlib

    root = pathlib.Path(targeted.__file__).parent
    for f in ("ingest.py", "feeds.py", "http.py", "extract.py"):
        assert "targeted" not in (root / f).read_text(encoding="utf-8")
