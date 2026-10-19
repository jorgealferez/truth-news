import asyncio

import httpx
import pytest

from truthnews.crawler.targeted import MAX_PAGES, lookup

UA = "truthnews-test/1.0 (+https://nosmienten.com/acerca)"
ROBOTS = "User-agent: *\nDisallow: /transparencia/\n"


def site(pages: dict[str, tuple[int, str]], seen: list):
    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.url.path, request.headers["user-agent"]))
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        status, body = pages.get(request.url.path, (404, "no"))
        return httpx.Response(status, text=body)

    return httpx.MockTransport(handler)


def run(start, pages, seen, **kw):
    args = dict(
        is_document=lambda url, text: "Contrato 2026/17" in text,
        reason="Los medios dan importes distintos del contrato",
        justification="dudas-entre-medios",
        claim="El contrato asciende a 3 millones",
        alternatives_tried=["datos abiertos del portal", "BOE", "nota de prensa"],
        user_agent=UA,
        delay=0,
        transport=site(pages, seen),
    )
    args.update(kw)
    return asyncio.run(lookup(start, **args))


def test_reaches_the_document_logs_every_url_and_stops():
    pages = {
        "/transparencia/": (
            200,
            '<a href="/transparencia/contratos">c</a> <a href="https://otro.es/x">x</a>',
        ),
        "/transparencia/contratos": (
            200,
            '<a href="/transparencia/c17">17</a><a href="/transparencia/c18">18</a>',
        ),
        "/transparencia/c17": (200, "Contrato 2026/17: 2.950.000 euros"),
    }
    seen = []
    hop = lambda links: next((u for u in links if "contratos" in u or "c17" in u), None)  # noqa: E731
    rec = run("https://ayto.es/transparencia/", pages, seen, next_hop=hop)
    assert rec.stopped == "documento-obtenido" and rec.document_url == "https://ayto.es/transparencia/c17"
    assert [v.url.rsplit("/", 1)[-1] for v in rec.visits] == ["", "contratos", "c17"]
    assert all(v.status == 200 and not v.robots_allowed for v in rec.visits)
    assert all(ua == UA for _, ua in seen)  # User-Agent honesto en todas las peticiones
    assert "/transparencia/c18" not in [p for p, _ in seen]  # nada mas tras obtenerlo
    payload = rec.as_payload()
    assert payload["robots_excluia"] and payload["justificacion"] == "dudas-entre-medios"
    assert payload["parada"] == "documento-obtenido" and len(payload["visitas"]) == 3


@pytest.mark.parametrize(
    ("status", "body", "stopped"),
    [
        (403, "prohibido", "bloqueo-403"),
        (429, "espera", "bloqueo-429"),
        (200, "Please complete the CAPTCHA", "desafio"),
    ],
)
def test_stops_at_technical_blocks(status, body, stopped):
    seen = []
    rec = run("https://ayto.es/transparencia/", {"/transparencia/": (status, body)}, seen)
    assert rec.stopped == stopped and rec.document_url is None and len(rec.visits) == 1


def test_page_cap_same_domain_and_no_path():
    loop_pages = {f"/p{i}": (200, f'<a href="/p{i + 1}">n</a>') for i in range(20)}
    seen = []
    rec = run("https://ayto.es/p0", loop_pages, seen, next_hop=lambda links: links[0], max_pages=50)
    assert rec.stopped == "tope-de-paginas" and len(rec.visits) == MAX_PAGES
    rec = run("https://ayto.es/p0", loop_pages, [], next_hop=lambda links: "https://otro.es/x")
    assert rec.stopped == "sin-camino" and len(rec.visits) == 1
    rec = run("https://ayto.es/p0", loop_pages, [])
    assert rec.stopped == "sin-camino"


def test_network_error_is_recorded():
    def boom(request):
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        raise httpx.ConnectError("caido")

    rec = asyncio.run(
        lookup(
            "https://ayto.es/x",
            is_document=lambda u, t: True,
            reason="r",
            justification="falta-de-pruebas",
            claim="c",
            alternatives_tried=["x"],
            user_agent=UA,
            transport=httpx.MockTransport(boom),
        )
    )
    assert rec.stopped == "error-red" and rec.visits[0].status is None and rec.visits[0].robots_allowed


@pytest.mark.parametrize(
    "kw",
    [{"justification": "curiosidad"}, {"alternatives_tried": []}, {"reason": " "}, {"claim": ""}],
)
def test_requires_justification_and_alternatives(kw):
    with pytest.raises(ValueError):
        run("https://ayto.es/x", {}, [], **kw)


def test_cli_prints_the_trace(monkeypatch, capsys):
    from truthnews import cli
    from truthnews.crawler import targeted

    pages = {
        "/t/": (200, '<a href="/t/c17">17</a>'),
        "/t/c17": (200, "Contrato 2026/17"),
    }
    real = targeted.lookup

    async def fake(url, **kw):
        return await real(url, **kw, delay=0, transport=site(pages, []))

    monkeypatch.setattr(targeted, "lookup", fake)
    argv = ["consulta-puntual", "https://ayto.es/t/", "--documento", "2026/17", "--siguiente", "c17"]
    argv += ["--motivo", "m", "--justificacion", "falta-de-pruebas", "--afirmacion", "a"]
    argv += ["--alternativa", "BOE"]
    assert cli.main(argv) == 0
    out = capsys.readouterr().out
    assert '"parada": "documento-obtenido"' in out and '"vias_alternativas": [\n    "BOE"' in out
