"""Publicidad: cliente de ads-service con un servicio falso, huecos en las plantillas y pagina /publicidad."""

import json
from datetime import UTC, datetime

import httpx
import pytest
from fastapi.testclient import TestClient

from truthnews import ads
from truthnews.config import Settings
from truthnews.models import Article, Outlet, Story
from truthnews.web.app import create_app

AD = {
    "ad_id": "a1",
    "advertiser": {"name": "Staydia", "kind": "own", "group_disclosure": "Marca del grupo Simvix"},
    "format": "native",
    "label": "Publicidad",
    "headline": "Alquila sin sorpresas",
    "body": "Pisos verificados.",
    "cta": "Ver pisos",
    "image_url": "https://img.example/x.png",
    "display_url": "simvixhotels.com",
    "click_url": "https://gw.example/ads/v1/c/tok",
    "view_url": "https://gw.example/ads/v1/v/tok",
    "why": "Se muestra por el tema de la noticia (vivienda). No usamos datos personales.",
}


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def fake(handler, clock=None):
    calls = []

    def wrapped(request):
        calls.append(request)
        return handler(request)

    client = ads.AdsClient(
        "https://ads.example", "clave", transport=httpx.MockTransport(wrapped), clock=clock or Clock()
    )
    return client, calls


def ok(slots=None):
    def handler(request):
        body = json.loads(request.content)
        out = {s: (slots or {}).get(s, AD) for s in body["slots"]}
        return httpx.Response(200, json={"request_id": "r", "ads": out})

    return handler


CTX = {"url": "https://nosmienten.com/historia/1", "keywords": ["vivienda"]}


def test_serve_ok_sends_contract_and_skips_null_slot():
    client, calls = fake(ok({"footer-strip": None}))
    got = client.serve(["story-inline", "footer-strip", "otro"], CTX, "v" * 64)
    assert set(got) == {"story-inline"}
    assert got["story-inline"]["headline"] == "Alquila sin sorpresas"
    req = calls[0]
    assert req.url == "https://ads.example/ads/v1/serve" and req.headers["X-Site-Key"] == "clave"
    body = json.loads(req.content)
    assert body["site"] == "nosmienten" and body["slots"] == ["story-inline", "footer-strip"]
    assert body["context"] == CTX and body["viewer"] == "v" * 64 and body["exclude_advertisers"] == []


def test_disabled_without_url_or_key_never_calls():
    assert not ads.AdsClient("", "clave").enabled and not ads.AdsClient("https://x", "").enabled
    assert ads.AdsClient("", "").serve(["story-inline"], CTX, "v") == {}
    client, calls = fake(ok())
    assert client.serve(["nada"], CTX, "v") == {} and calls == []


@pytest.mark.parametrize(
    "handler",
    [
        lambda r: httpx.Response(500),
        lambda r: httpx.Response(200, text="no es json"),
        lambda r: httpx.Response(200, json={"sin": "ads"}),
    ],
)
def test_errors_mean_no_ads_and_are_cached(handler):
    client, calls = fake(handler)
    assert client.serve(["story-inline"], CTX, "v") == {}
    assert client.serve(["story-inline"], CTX, "v") == {}
    assert len(calls) == 1  # el error se recuerda 60 s para esa pagina


def test_timeout_means_no_ads():
    def boom(request):
        raise httpx.ReadTimeout("lento", request=request)

    client, _ = fake(boom)
    assert client.serve(["story-inline"], CTX, "v") == {}

    clock = Clock()

    def slow(request):
        clock.now += 0.2  # responde, pero tarde: no se espera a pintar
        return ok()(request)

    client, _ = fake(slow, clock)
    assert client.serve(["story-inline"], CTX, "v") == {}


def test_circuit_breaker_opens_after_three_failures():
    clock = Clock()
    client, calls = fake(lambda r: httpx.Response(503), clock)
    for i in range(3):
        client.serve(["story-inline"], {**CTX, "url": f"u{i}"}, "v")
    assert len(calls) == 3
    assert client.serve(["story-inline"], {**CTX, "url": "otra"}, "v") == {}
    assert len(calls) == 3  # abierto: 60 s sin llamar
    clock.now += 61
    client.serve(["story-inline"], {**CTX, "url": "otra"}, "v")
    assert len(calls) == 4


def test_success_resets_failure_count_and_error_cache_expires():
    clock = Clock()
    state = {"fail": True}

    def flaky(request):
        return httpx.Response(500) if state["fail"] else ok()(request)

    client, calls = fake(flaky, clock)
    client.serve(["story-inline"], CTX, "v")
    client.serve(["story-inline"], {**CTX, "url": "b"}, "v")
    state["fail"] = False
    assert client.serve(["story-inline"], {**CTX, "url": "c"}, "v")  # exito: contador a cero
    state["fail"] = True
    client.serve(["story-inline"], {**CTX, "url": "d"}, "v")
    client.serve(["story-inline"], {**CTX, "url": "e"}, "v")
    assert len(calls) == 5 and client.serve(["story-inline"], {**CTX, "url": "f"}, "v") == {}
    assert len(calls) == 6  # solo dos fallos seguidos antes: aun cerrado
    state["fail"] = False
    clock.now += 61
    assert client.serve(["story-inline"], CTX, "v")  # el error de CTX caduco


def test_clean_ad_rejects_unsafe_and_forces_label():
    assert ads._clean_ad(None) is None
    assert ads._clean_ad({**AD, "click_url": "http://inseguro"}) is None
    assert ads._clean_ad({**AD, "view_url": "javascript:x"}) is None
    assert ads._clean_ad({**AD, "headline": " "}) is None
    ad = ads._clean_ad({**AD, "label": "", "format": "raro", "image_url": "http://x", "advertiser": "x"})
    assert ad["label"] == "Publicidad" and ad["format"] == "native" and ad["image_url"] == ""
    assert ad["advertiser"]["kind"] == "third"


def test_viewer_hash_is_daily_truncated_and_opaque():
    d1, d2 = datetime(2026, 10, 19, tzinfo=UTC), datetime(2026, 10, 20, tzinfo=UTC)
    a = ads.viewer_hash("81.40.12.7", "UA", d1)
    assert a == ads.viewer_hash("81.40.12.200", "UA", d1)  # misma /24
    assert a != ads.viewer_hash("81.40.13.7", "UA", d1) and a != ads.viewer_hash("81.40.12.7", "UB", d1)
    assert a != ads.viewer_hash("81.40.12.7", "UA", d2)  # la sal cambia cada dia
    assert len(a) == 64 and "81.40" not in a
    assert ads._truncate_ip("2a01:4f8:1:2:3::1") == "2a01:4f8:1::" and ads._truncate_ip("x") == ""
    assert ads.client_ip({"x-forwarded-for": "1.2.3.4, 10.0.0.1"}, "10.0.0.1") == "1.2.3.4"
    assert ads.client_ip({}, None) == ""


def test_keywords_and_context():
    kw = ads.keywords(["Sube el alquiler de la vivienda", "La vivienda y el alquiler en 2026"])
    assert kw[:2] == ["alquiler", "vivienda"] and "el" not in kw and "2026" not in kw
    ctx = ads.page_context("https://n/historia/1", "Titular", None, ["vivienda"], "ES", "es")
    assert ctx["category"] == "" and ctx["keywords"] == ["titular", "vivienda"]


# --- Plantillas ---------------------------------------------------------------------------------------


@pytest.fixture()
def seeded(session):
    o = Outlet(slug="m", name="Medio", homepage="https://m.es", country="ES", language="es", scope="nacional")
    session.add(o)
    session.flush()
    now = datetime.now(UTC)
    st = Story(
        title="El alquiler de la vivienda sube",
        category="economia",
        country="ES",
        first_seen=now,
        last_seen=now,
        n_articles=8,
        n_outlets=1,
    )
    session.add(st)
    session.flush()
    for i in range(8):
        session.add(
            Article(
                outlet_id=o.id,
                url=f"https://m.es/{i}",
                url_hash=f"h{i:062d}",
                title=f"Vivienda y alquiler {i}",
                summary="El precio del alquiler",
                published_at=now,
                language="es",
                country="ES",
                category="economia",
                topics=[],
                story_id=st.id,
            )
        )
    session.commit()
    return st


def app_with(engine, handler):
    client, calls = fake(handler)
    return TestClient(create_app(Settings(database_url="sqlite://"), engine=engine, ads_client=client)), calls


def test_story_inline_after_comparison_labelled_and_sponsored(engine, seeded):
    tc, calls = app_with(engine, ok())
    r = tc.get(f"/historia/{seeded.id}", headers={"user-agent": "UA", "x-forwarded-for": "81.40.12.7"})
    page = r.text
    assert r.status_code == 200 and "set-cookie" not in r.headers
    body = json.loads(calls[0].content)
    assert body["slots"] == ["story-inline", "footer-strip"]
    assert body["context"]["category"] == "economia" and "vivienda" in body["context"]["keywords"]
    assert f"/historia/{seeded.id}-" in body["context"]["url"] and len(body["viewer"]) == 64
    assert page.count('rel="sponsored noopener"') == 2 and page.count('<span class="ad-tag">Publicidad') == 2
    assert "Marca del grupo Simvix" in page and "Por qué veo esto" in page and "simvixhotels.com" in page
    assert 'data-ad-view="https://gw.example/ads/v1/v/tok"' in page and "/static/ads.js" in page
    inline = page.index("ad-story-inline")
    assert page.index("Cómo lo cuenta cada medio") < inline < page.index("ad-footer-strip")
    assert inline > page.index("<h1")  # nunca encima del titular


def test_no_ad_no_slot(engine, seeded):
    tc, _ = app_with(engine, ok({"story-inline": None, "footer-strip": None, "list-native": None}))
    for path in (f"/historia/{seeded.id}", "/seccion/economia"):
        page = tc.get(path).text
        assert 'class="ad ' not in page and "ads.js" not in page and "Publicidad</a>" in page  # pie
    tc, _ = app_with(engine, lambda r: httpx.Response(500))
    assert 'class="ad ' not in tc.get(f"/historia/{seeded.id}").text


def test_list_native_after_sixth_item_once(engine, seeded):
    tc, calls = app_with(engine, ok({"footer-strip": None}))
    for path in ("/seccion/economia", "/pais/ES", "/medio/m"):
        page = tc.get(path).text
        assert page.count("ad-list-native") == 1, path
        assert (
            page.index("Vivienda y alquiler 2")
            < page.index("ad-list-native")
            < page.index("Vivienda y alquiler 1")
        )  # orden: 7, 6, 5, 4, 3, 2 | anuncio | 1, 0
    assert json.loads(calls[0].content)["slots"] == ["list-native", "footer-strip"]
    assert "ad-list-native" not in tc.get("/region/ES-MD").text  # menos de 6 elementos: sin anuncio
    assert tc.get("/").status_code == 200 and tc.get("/analisis").status_code == 200


def test_advertising_page_and_links(engine):
    tc = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    page = tc.get("/publicidad").text
    assert "Publicidad en nosmienten.com" in page and "Ley 34/2002" in page and "artículo 9" in page
    assert "sin cookies ni perfiles" in page and "nunca influye en los veredictos" in page
    assert (
        "No aceptamos publicidad política" in page
        and "las páginas sobre elecciones no llevan anuncios" in page
    )
    assert "github.com/jorgealferez/truth-news" in page and "IntersectionObserver" not in page
    js = tc.get("/static/ads.js")
    assert js.status_code == 200 and "IntersectionObserver" in js.text and "keepalive: true" in js.text
    for path in ("/metodologia", "/acerca"):
        assert 'href="/publicidad"' in tc.get(path).text
    assert "/publicidad" in tc.get("/sitemaps/paginas-1.xml").text
    assert "Advertising on nosmienten.com" in tc.get("/publicidad?lang=en").text


# --- Neutralidad (condiciones de la direccion, 2026-10-19) ----------------------------------------------


def test_political_or_institutional_ads_are_rejected():
    assert ads._clean_ad({**AD, "headline": "Vota por el cambio"}) is None
    assert ads._clean_ad({**AD, "advertiser": {"name": "Partido Ejemplo", "kind": "third"}}) is None
    assert ads._clean_ad({**AD, "advertiser": {"name": "X", "kind": "third", "category": "Politica"}}) is None
    assert ads._clean_ad({**AD, "body": "Campaña del Ministerio de Sanidad"}) is None
    assert ads._clean_ad({**AD, "category": "institutional"}) is None
    assert ads._clean_ad(AD) is not None  # marca propia de hoteles: pasa


def test_ad_image_only_from_the_ad_gateway():
    other = ads._clean_ad({**AD, "image_url": "https://tracker.example/pixel.png"})
    assert other["image_url"] == ""  # otro host: sin rastreadores de terceros
    same = ads._clean_ad({**AD, "image_url": "https://gw.example/img/1.png"})
    assert same["image_url"] == "https://gw.example/img/1.png"


def test_election_pages_get_no_ads_and_no_call(engine, seeded, session):
    seeded.title = "Sondeo de las elecciones generales: así votarían"
    session.commit()
    tc, calls = app_with(engine, ok())
    page = tc.get(f"/historia/{seeded.id}").text
    assert calls == [] and 'class="ad ' not in page
    assert ads.sensitive(["La campaña electoral arranca"]) and not ads.sensitive(["Sube el alquiler"])


def test_no_story_inline_next_to_verdicts(engine, seeded, session):
    from truthnews.models import Article, Claim, Verification

    a = session.query(Article).filter_by(story_id=seeded.id).first()
    c = Claim(
        article_id=a.id,
        story_id=seeded.id,
        outlet_id=a.outlet_id,
        text="El alquiler sube un 12 %",
        indicator="paro",
        geo="ES",
        value=12.0,
        unit="pct",
    )
    session.add(c)
    session.flush()
    session.add(Verification(claim_id=c.id, verdict="falso", confidence=0.8, explanation="x", method="nivel"))
    session.commit()
    tc, calls = app_with(engine, ok())
    page = tc.get(f"/historia/{seeded.id}").text
    assert json.loads(calls[0].content)["slots"] == ["footer-strip"]
    assert "ad-story-inline" not in page and "ad-footer-strip" in page
