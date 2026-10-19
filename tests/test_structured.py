import re
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from truthnews.config import Settings
from truthnews.models import Article, Claim, Entity, Evidence, Outlet, Story, Verification
from truthnews.web import seo, structured
from truthnews.web.app import create_app

SITE = "http://localhost:8000"


def _meta(html: str, attr: str, name: str) -> str | None:
    m = re.search(rf'<meta {attr}="{re.escape(name)}" content="([^"]*)">', html)
    return m.group(1) if m else None


def _canonical(html: str) -> str:
    return re.search(r'<link rel="canonical" href="([^"]*)">', html).group(1)


@pytest.fixture()
def site(engine, session):
    now = datetime.now(UTC)
    o = Outlet(
        slug="medio", name="Medio", homepage="https://m.es", country="ES", language="es", scope="national"
    )
    session.add(o)
    st = Story(
        title="Disturbios en Paris",
        category="politica",
        country="ES",
        first_seen=now,
        last_seen=now,
        n_articles=2,
        n_outlets=2,
    )
    session.add(st)
    session.flush()
    art = Article(
        outlet_id=o.id,
        url="https://m.es/1",
        url_hash="a" * 64,
        title="El paro sube al 12 %",
        published_at=now,
        language="es",
        country="ES",
        category="politica",
        topics=[],
        story_id=st.id,
    )
    session.add(art)
    session.flush()
    claims = {}
    for value, verdict in ((12.0, "falso"), (13.0, "sin-datos")):
        c = Claim(
            article_id=art.id,
            story_id=st.id,
            outlet_id=o.id,
            text=f"La tasa de paro es del {value:.0f} % </script>",
            indicator="paro",
            geo="ES",
            value=value,
            unit="pct",
        )
        session.add(c)
        session.flush()
        v = Verification(claim_id=c.id, verdict=verdict, confidence=0.8, explanation="x", method="nivel")
        if verdict == "falso":
            v.evidence.append(
                Evidence(
                    source="eurostat",
                    label="Tasa de paro",
                    url="https://ec.europa.eu/x",
                    period="2026-08",
                    value=10.0,
                    payload={},
                )
            )
        session.add(v)
        claims[verdict] = c
    speaker = Entity(key="persona:ana perez", kind="persona", name="Ana Pérez", curated=True)
    session.add(speaker)
    session.flush()
    claims["falso"].speaker_entity_id = speaker.id
    session.commit()
    return TestClient(create_app(Settings(database_url="sqlite://"), engine=engine)), st, claims


def test_home_declares_organization_and_website(site):
    c, _, _ = site
    html = c.get("/").text
    (org,) = structured.of_type(html, "NewsMediaOrganization")
    assert org["name"] == "NosMienten" and org["logo"]["url"] == f"{SITE}/static/icon-512.png"
    assert org["publishingPrinciples"] == f"{SITE}/metodologia"
    (web,) = structured.of_type(html, "WebSite")
    assert web["publisher"]["@id"] == org["@id"] and web["inLanguage"] == "es"
    assert "max-image-preview:large" in _meta(html, "name", "robots")
    assert _canonical(html) == f"{SITE}/" and _meta(html, "property", "og:url") == f"{SITE}/"
    assert not structured.of_type(c.get("/medios").text, "NewsMediaOrganization")  # solo en portada


def test_claim_review_on_verifications_with_verdict(site):
    c, _, claims = site
    cl = claims["falso"]
    html = c.get(f"/verificacion/{cl.id}").text
    assert "</script> <" not in html.split("ld+json")[1].split("</script>")[0]  # no cierra el script
    (rev,) = structured.of_type(html, "ClaimReview")
    assert rev["url"] == f"{SITE}/verificacion/{cl.id}" and rev["claimReviewed"] == cl.text
    assert rev["reviewRating"] == {
        "@type": "Rating",
        "ratingValue": 1,
        "bestRating": 4,
        "worstRating": 1,
        "alternateName": "Falso",
    }
    item = rev["itemReviewed"]
    assert item["author"] == {"@type": "Organization", "name": "Medio", "url": "https://m.es"}
    assert item["appearance"][0]["url"] == "https://m.es/1" and item["datePublished"].endswith("+00:00")
    assert rev["datePublished"] and rev["author"]["name"] == "NosMienten"
    assert _canonical(html) == f"{SITE}/verificacion/{cl.id}"
    assert _meta(html, "property", "og:type") == "article"
    crumbs = structured.of_type(html, "BreadcrumbList")[0]["itemListElement"]
    assert [i["item"] for i in crumbs] == [
        f"{SITE}/",
        f"{SITE}/verificaciones",
        f"{SITE}/verificacion/{cl.id}",
    ]
    no_data = c.get(f"/verificacion/{claims['sin-datos'].id}").text
    assert not structured.of_type(no_data, "ClaimReview")
    assert rev["citation"] == [
        {"@type": "Dataset", "name": "eurostat · Tasa de paro · 2026-08", "url": "https://ec.europa.eu/x"}
    ]


def test_internal_links_story_verification_and_entity(site):
    c, st, claims = site
    cl = claims["falso"]
    page = c.get(f"/verificacion/{cl.id}").text
    story_url = seo.path("historia", st.id, st.title)
    assert f'<a href="{story_url}">{st.title}</a>' in page  # ancla descriptiva y URL canonica
    assert f'href="/historia/{st.id}"' not in page  # sin el enlace sin slug (301)
    assert 'href="/entidad/' in page and "Ana Pérez" in page
    story = c.get(story_url).text
    assert f'<a href="/verificacion/{cl.id}"><strong>' in story  # el veredicto en una frase es el enlace


def test_story_breadcrumbs_and_canonical(site):
    c, st, _ = site
    want = seo.path("historia", st.id, st.title)
    html = c.get(want).text
    assert _canonical(html) == SITE + want == _meta(html, "property", "og:url")
    assert html.count('rel="canonical"') == 1
    crumbs = structured.of_type(html, "BreadcrumbList")[0]["itemListElement"]
    assert crumbs[-1]["item"] == f"{SITE}/seccion/politica"
    assert '<p class="crumbs"><a href="/">' in html


def test_lists_have_crumbs_descriptions_and_paged_canonicals(site):
    c, _, _ = site
    outlet = c.get("/medio/medio").text
    names = [i["name"] for i in structured.of_type(outlet, "BreadcrumbList")[0]["itemListElement"]]
    assert names[1] == "Medios" and names[-1] == "Medio"
    assert _meta(outlet, "name", "description").startswith("Medio: ")
    region = c.get("/region/ES-MD").text
    items = structured.of_type(region, "BreadcrumbList")[0]["itemListElement"]
    assert items[1]["item"] == f"{SITE}/pais/ES"
    assert _canonical(c.get("/seccion/politica?page=2").text) == f"{SITE}/seccion/politica?page=2"
    assert _canonical(c.get("/seccion/politica?page=1").text) == f"{SITE}/seccion/politica"


def test_pages_in_unindexed_language_stay_noindex(site):
    c, _, _ = site
    html = c.get("/en/medios").text
    assert _meta(html, "name", "robots") == "noindex, follow"


def test_jsonld_helpers():
    assert structured.jsonld() == ""
    out = str(
        structured.jsonld(
            {"@context": "https://schema.org", "@type": "Thing", "name": "a</script>b", "x": None}
        )
    )
    assert "<\\/script>" in out and '"x"' not in out
    graph = structured.extract(out + str(structured.jsonld({"@type": "A"}, {"@type": "B", "list": []})))
    assert [o["@type"] for o in graph] == ["Thing", "A", "B"] and "list" not in graph[2]
    assert structured.RATING == {"falso": 1, "enganoso": 2, "impreciso": 3, "verdadero": 4}
    assert structured.breadcrumbs(Settings(database_url="sqlite://"), [("Portada", "/")], "/") is None
    assert (
        structured.iso(None) == ""
        and structured.iso(datetime(2026, 1, 2, 3, 4, 5, 6)) == "2026-01-02T03:04:05+00:00"
    )
