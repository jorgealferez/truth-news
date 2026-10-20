"""Publicidad propia de Ridelta por zona (ADR 0055): zona del lector, banners, patrocinado y paginas."""

import json
import re
from datetime import UTC, datetime
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
from fastapi.testclient import TestClient

from truthnews import ads, house
from truthnews.config import Settings
from truthnews.models import Article, Outlet, Story
from truthnews.web.app import create_app

# --- Registro y zona del lector ------------------------------------------------------------------------


def test_registry_matches_vtc_clm_and_only_contracted_zones():
    z = house.zones()
    provinces = {p.slug: p.domain for p in house.provinces()}
    assert provinces["toledo"] == "taxitoledo.app" and provinces["soria"] == "taxisoria.app"
    assert len(provinces) == 14 and "madrid" not in provinces  # Madrid: solo con socios, fuera
    assert {r.domain for r in house.regions()} == {"vtcclm.com", "vtccyl.com"}
    assert z[house.GENERIC].domain == "ridelta.com"
    for r in house.regions():  # cada provincia de una comunidad existe y apunta a su hub
        assert all(z[p].hub == r.slug for p in r.provinces)
    for p in house.provinces():
        assert p.towns and p.intro and p.demand and p.domain.endswith(".app")


@pytest.mark.parametrize(
    "lat,lon,slug",
    [
        (40.1233, -3.8481, "toledo"),  # Illescas
        (40.0972, -3.7003, "toledo"),  # Sesena
        (41.6523, -4.7245, "valladolid"),
        (40.6331, -3.1669, "guadalajara"),
        (39.0, -1.86, "albacete"),
    ],
)
def test_nearest_town_inside_radius(lat, lon, slug):
    assert house.nearest(lat, lon).slug == slug


def test_nearest_outside_every_zone_is_none():
    assert house.nearest(41.3874, 2.1686) is None  # Barcelona
    assert house.nearest(37.3891, -5.9845) is None  # Sevilla


def test_content_reads_towns_and_skips_ambiguous_names():
    assert house.from_content(["Corte de luz en Illescas y Seseña"]).slug == "toledo"
    assert house.from_content(["Accidente en la A-62 cerca de Medina del Campo"]).slug == "valladolid"
    assert house.from_content(["Feria taurina: el toro de la tarde"]) is None  # Toro (Zamora) no cuenta
    assert house.from_content(["Paro en la comunidad"], ["ES-CL"]).slug == "castilla-y-leon"
    assert house.from_content(["Paro en la comunidad"], ["ES-MD"]) is None
    # Mas municipios de una provincia ganan
    assert house.from_content(["Toledo", "Burgos y Aranda de Duero"]).slug == "burgos"


def test_resolve_order_choice_then_content_then_generic():
    assert house.resolve("cuenca", ["Illescas"]) == (house.zones()["cuenca"], "chosen")
    assert house.resolve(None, ["Illescas"]) == (house.zones()["toledo"], "content")
    assert house.resolve("../etc", []) == (house.zones()[house.GENERIC], "generic")
    assert house.resolve("desconocida", []) == (house.zones()[house.GENERIC], "generic")


# --- Banners y enlaces --------------------------------------------------------------------------------


def test_creatives_rotate_to_the_zone_site_with_utm():
    toledo = house.zones()["toledo"]
    cs = house.creatives(toledo)
    assert len(cs) == 5 and len({c["key"] for c in cs}) == 5
    assert cs[0]["url"].startswith("https://taxitoledo.app/pedir?")
    q = parse_qs(urlsplit(cs[0]["url"]).query)
    assert q == {
        "utm_source": ["nosmienten"],
        "utm_medium": ["banner"],
        "utm_campaign": ["ridelta-toledo"],
        "utm_content": ["precio"],
    }
    assert any(c["url"].startswith("https://ridelta.com/apps?") for c in cs)
    generic = house.creatives(house.zones()[house.GENERIC])
    assert generic[0]["url"].startswith("https://ridelta.com/cobertura?")
    region = house.creatives(house.zones()["castilla-y-leon"])
    assert region[0]["url"].startswith("https://vtccyl.com?") and "Soria" in region[0]["body"]
    en = house.creatives(toledo, "en")
    assert en[0]["headline"] == "Toledo: fixed-price rides"


def test_apps_are_announced_as_they_are(monkeypatch):
    """Mientras ridelta.com/apps diga 'en preparacion', no se anuncia una app de tienda."""
    txt = " ".join(c["body"] for c in house.creatives(house.zones()["toledo"]))
    assert "se instala como app" in txt and "App Store" not in txt
    art = house.article("como-funciona-ridelta-en-toledo")
    assert "en preparación para las tiendas" in json.dumps(art, ensure_ascii=False)


def test_fill_keeps_ads_service_first_and_fills_the_rest():
    zone = house.zones()["toledo"]
    served = {"footer-strip": {"headline": "De ads-service"}}
    out = house.fill(("list-native", "footer-strip", "story-inline"), served, zone, "content")
    assert out["footer-strip"] == served["footer-strip"]
    assert out["list-native"]["teaser"] and out["list-native"]["url"].startswith("/patrocinado/")
    assert out["story-inline"]["house"] and out["story-inline"]["label"] == "Publicidad"


# --- Contenido patrocinado ----------------------------------------------------------------------------


def test_one_generic_two_per_province_one_per_region():
    arts = house.articles()
    assert len(arts) == 2 + 2 + 14 * 2
    assert len({a["slug"] for a in arts}) == len(arts)
    assert [a["slug"] for a in arts[:2]] == ["donde-no-llegan-las-grandes", "como-funciona-ridelta"]
    for a in arts:
        assert a["title"] and a["dek"] and a["links"] and all(u.startswith("https://") for _, u in a["links"])
    toledo = house.articles_for(house.zones()["toledo"])
    assert [a["zone"] for a in toledo][:3] == ["toledo", "toledo", "castilla-la-mancha"]
    assert {a["slug"] for a in toledo[-2:]} == {"donde-no-llegan-las-grandes", "como-funciona-ridelta"}


def test_articles_invent_no_prices_or_availability():
    text = json.dumps(house.articles(), ensure_ascii=False)
    assert not re.search(r"\d+\s?(€|euros?)\b", text)
    for promise in ("24 horas", "al instante", "inmediat", "garantizad", "el más barato", "ganar"):
        assert promise not in text.lower(), promise


# --- En la web ----------------------------------------------------------------------------------------


@pytest.fixture()
def seeded(session):
    o = Outlet(
        slug="lt",
        name="La Tribuna",
        homepage="https://lt.es",
        country="ES",
        language="es",
        scope="local",
        region="ES-CM",
    )
    session.add(o)
    session.flush()
    now = datetime.now(UTC)
    st = Story(
        title="Obras en la A-42 entre Illescas y Yuncos",
        category="sociedad",
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
                url=f"https://lt.es/{i}",
                url_hash=f"t{i:062d}",
                title=f"Corte en Illescas {i}",
                summary="Trafico en la A-42",
                published_at=now,
                language="es",
                country="ES",
                region="ES-CM",
                category="sociedad",
                topics=[],
                story_id=st.id,
            )
        )
    session.commit()
    return st


def client(engine, **kw):
    return TestClient(create_app(Settings(database_url="sqlite://", **kw), engine=engine))


def test_story_banner_goes_to_the_zone_of_the_content(engine, seeded):
    tc = client(engine)
    page = tc.get(f"/historia/{seeded.id}").text
    assert page.count("ad-house") == 2  # dentro de la historia y franja del pie
    assert "https://taxitoledo.app/pedir?utm_source=nosmienten" in page
    assert 'rel="sponsored noopener"' in page and "Publicidad" in page and "Marca del grupo Simvix" in page
    assert "/static/house.js" in page and "Usar mi ubicación" in page and 'href="/zona/soria?to=' in page
    assert "Se muestra por la zona de la que trata esta página" in page


def test_list_native_is_the_sponsored_piece_of_the_zone(engine, seeded):
    page = client(engine).get("/region/ES-CM").text
    assert page.count("ad-list-native") == 1 and "Contenido patrocinado" in page
    assert 'href="/patrocinado/como-funciona-ridelta-en-toledo"' in page


def test_chosen_zone_wins_and_can_be_forgotten(engine, seeded):
    tc = client(engine)
    r = tc.get("/zona/burgos?to=/historia/1", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/historia/1"
    assert "zona=burgos" in r.headers["set-cookie"] and r.headers["x-robots-tag"] == "noindex"
    page = tc.get(f"/historia/{seeded.id}").text
    assert "https://taxiburgos.app/pedir?" in page and "taxitoledo.app" not in page
    assert "Es la zona que elegiste" in page and "Olvidar mi zona" in page
    r = tc.get("/zona/olvidar?to=/", follow_redirects=False)
    assert 'zona=""' in r.headers["set-cookie"] or "Max-Age=0" in r.headers["set-cookie"]


def test_zone_route_ignores_unknown_zones_and_external_targets(engine):
    tc = client(engine)
    r = tc.get("/zona/marte?to=//malo.example", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/" and "set-cookie" not in r.headers
    assert "Disallow: /zona/" in tc.get("/robots.txt").text


def test_generic_when_nothing_is_known(engine, seeded):
    page = client(engine).get("/analisis").text
    assert "https://ridelta.com/cobertura?utm_source=nosmienten" in page
    assert "No sabemos tu zona" in page


def test_no_house_ads_on_election_pages(engine, seeded, session):
    st = Story(
        title="Elecciones generales: los candidatos en Illescas",
        category="politica",
        country="ES",
        first_seen=datetime.now(UTC),
        last_seen=datetime.now(UTC),
        n_articles=1,
        n_outlets=1,
    )
    session.add(st)
    session.commit()
    assert "ad-house" not in client(engine).get(f"/historia/{st.id}").text


def test_switch_off_and_ads_service_keeps_priority(engine, seeded):
    assert "ad-house" not in client(engine, house_ads_enabled=False).get(f"/historia/{seeded.id}").text

    def handler(request):
        slots = json.loads(request.content)["slots"]
        ad = {
            "headline": "Anuncio de ads-service",
            "click_url": "https://gw.example/c",
            "view_url": "https://gw.example/v",
            "advertiser": {"name": "Staydia", "kind": "own"},
        }
        return httpx.Response(200, json={"ads": {s: ad if s == "footer-strip" else None for s in slots}})

    svc = ads.AdsClient("https://ads.example", "clave", transport=httpx.MockTransport(handler))
    tc = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine, ads_client=svc))
    page = tc.get(f"/historia/{seeded.id}").text
    assert "Anuncio de ads-service" in page and page.count("ad-house") == 1  # el pie es de ads-service


def test_sponsored_pages_are_labelled_and_linked_as_sponsored(engine):
    tc = client(engine)
    r = tc.get("/patrocinado/como-funciona-ridelta-en-toledo")
    page = r.text
    assert r.status_code == 200 and "<title>Cómo funciona Ridelta en Toledo" in page
    assert page.count("Contenido patrocinado") >= 2 and "Patrocinado por" in page
    assert "Esto es publicidad" in page and "taxitoledo.app" in page and "vtcclm.com" in page
    links = re.findall(r'<a href="(https://[^"]+)" rel="([^"]+)"', page)
    assert links and all("sponsored" in rel for _, rel in links)
    assert all("utm_medium=patrocinado" in href for href, _ in links if "ridelta" in href or ".app" in href)
    assert tc.get("/patrocinado/no-existe").status_code == 404
    index = tc.get("/patrocinado").text
    assert index.count('href="/patrocinado/') == len(house.articles())
    assert 'href="/patrocinado"' in tc.get("/acerca").text  # enlace en el pie


def test_sponsored_index_puts_the_chosen_zone_first(engine):
    tc = client(engine)
    tc.get("/zona/leon", follow_redirects=False)
    index = tc.get("/patrocinado").text
    assert "Tu zona: León" in index
    assert index.index("ridelta-en-leon") < index.index("ridelta-en-toledo")


def test_sponsored_in_general_sitemap_never_in_google_news(engine):
    tc = client(engine)
    assert "/patrocinado/como-funciona-ridelta-en-soria" in tc.get("/sitemaps/paginas-1.xml").text
    assert "patrocinado" not in tc.get("/sitemaps/news.xml").text
    assert "patrocinado" not in tc.get("/rss.xml").text


def test_zones_json_for_the_browser_and_policy_pages(engine):
    tc = client(engine)
    data = tc.get("/zonas.json").json()
    assert data["radius_km"] == 45 and len(data["zones"]) == 14
    assert data["zones"][0]["towns"][0][0] == "Illescas"
    js = tc.get("/static/house.js").text
    assert "getCurrentPosition" in js and "prefers-reduced-motion" in js and 'credentials: "omit"' in js
    assert "Publicidad propia por zona" in tc.get("/publicidad").text
    assert "<code>zona</code>" in tc.get("/cookies").text


def test_where_the_big_platforms_do_not_go_stays_true():
    """La frase solo sale si ningun municipio de la zona esta en la lista de la gran plataforma."""
    assert all(house.outside_big(p) for p in house.provinces())
    assert all(house.outside_big(r) for r in house.regions())
    rural = house.article("donde-no-llegan-las-grandes")
    text = json.dumps(rural, ensure_ascii=False)
    assert "Cabify" in text and "cabify.com, consultada el 19 de octubre de 2026" in text
    assert "los primeros" not in text and "únicos" not in text  # sin superlativos que no se pueden probar
    toledo = house.zones()["toledo"]
    assert house.small_towns(toledo)[-1] == "Villacañas" and "Illescas" not in house.small_towns(toledo)
    assert any(c["key"] == "pueblos" for c in house.creatives(toledo))
    # Si la plataforma llegara a una zona, su pieza deja de decirlo
    fake = house.Zone(slug="x", name="X", domain="x.app", kind="province", towns=(("Valencia", 39.4, -0.3),))
    assert not house.outside_big(fake)
