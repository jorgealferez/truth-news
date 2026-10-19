from datetime import timedelta
from types import SimpleNamespace as NS

from truthnews.analysis.repeated import group, key_of, repeated, repeated_for_story, slug_of
from truthnews.models import Article, Claim, Evidence, Outlet, Story, Verification, utcnow

NOW = utcnow()


def ns_claim(
    article_id,
    outlet,
    value,
    days=0,
    verdict=None,
    checked_minutes=0,
    geo="ES",
    period="2026-09",
    speaker=None,
):
    v = None
    if verdict:
        v = NS(verdict=verdict, checked_at=NOW - timedelta(minutes=checked_minutes), evidence=[])
    return NS(
        indicator="inflacion",
        geo=geo,
        unit="pct",
        period=period,
        value=value,
        article_id=article_id,
        article=NS(published_at=NOW - timedelta(days=days)),
        outlet=NS(name=outlet),
        verification=v,
        speaker_entity_id=speaker,
    )


def test_group_same_figure_in_two_articles():
    claims = [
        ns_claim(1, "A", 4.9, days=2, verdict="verdadero", checked_minutes=50),
        ns_claim(2, "B", 4.94, days=1, verdict="impreciso", checked_minutes=5),  # misma cifra a una decima
        ns_claim(3, "A", 4.9),
        ns_claim(4, "C", 10.3),  # otra cifra, una sola vez
        ns_claim(5, "D", 4.9, geo="FR"),  # otro territorio
        ns_claim(6, "E", 4.9, period="2026-08"),  # otro periodo
    ]
    (r,) = group(claims)
    assert r.outlets == ["A", "B"] and len(r.claims) == 3 and r.days == 3
    assert r.verdict == "impreciso"  # el mas reciente con dato
    assert r.example.article_id == 1 and r.first < r.last
    assert r.slug == slug_of(key_of(claims[0])) == "inflacion-ES-2026-09-4_9-pct"
    # La misma cifra dicha por un ministro y por una ONG son dos afirmaciones distintas.
    two = group(
        [ns_claim(1, "A", 4.9, speaker=7), ns_claim(2, "B", 4.9, speaker=8), ns_claim(3, "C", 4.9, speaker=7)]
    )
    assert [(r.outlets, r.key[-1]) for r in two] == [(["A", "C"], 7)] and two[0].slug.endswith("-h7")
    # La misma afirmacion dos veces en el mismo articulo no es repetirse.
    assert group([ns_claim(1, "A", 4.9), ns_claim(1, "A", 4.9)]) == []
    assert group([ns_claim(1, "A", 4.9, verdict="sin-datos"), ns_claim(2, "B", 4.9)])[0].verdict is None


def _db(session):
    now = utcnow()
    outs = []
    for slug in ("a", "b"):
        o = Outlet(
            slug=slug, name=slug.upper(), homepage="https://x", country="ES", language="es", scope="national"
        )
        session.add(o)
        outs.append(o)
    st = Story(
        title="Inflacion",
        category="economia",
        country="ES",
        first_seen=now,
        last_seen=now,
        n_articles=1,
        n_outlets=1,
    )
    session.add(st)
    session.flush()
    for i, (o, story, verdict) in enumerate([(outs[0], st, "falso"), (outs[1], None, None)]):
        a = Article(
            outlet_id=o.id,
            url=f"https://x/{i}",
            url_hash=f"r{i}".ljust(64, "_"),
            title=f"Titular {i}",
            published_at=now - timedelta(days=i),
            language="es",
            country="ES",
            category="economia",
            topics=[],
            story_id=story.id if story else None,
        )
        session.add(a)
        session.flush()
        c = Claim(
            article_id=a.id,
            story_id=a.story_id,
            outlet_id=o.id,
            text="La inflación está en el 10,3 %",
            indicator="inflacion",
            geo="ES",
            value=10.3,
            unit="pct",
            period="2026-09",
        )
        session.add(c)
        session.flush()
        if verdict:
            v = Verification(claim_id=c.id, verdict=verdict, confidence=0.9, explanation="x", method="nivel")
            v.evidence.append(
                Evidence(
                    source="ine",
                    label="Inflación interanual",
                    url="https://ine.es/ipc",
                    period="2026-09",
                    value=4.9,
                )
            )
            session.add(v)
    session.commit()
    return st


def test_queries_and_pages(engine, session):
    from fastapi.testclient import TestClient

    from truthnews.config import Settings
    from truthnews.web.app import create_app

    st = _db(session)
    (r,) = repeated(session)
    assert r.outlets == ["B", "A"] and r.verdict == "falso"
    assert [x.slug for x in repeated_for_story(session, st.id)] == [r.slug]
    assert repeated_for_story(session, 99999) == []
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    page = client.get("/repetidas").text
    assert "Afirmaciones que se repiten" in page and "10,3 %" in page and "en 2 medios · 2 días" in page
    assert "Falso" in page and "https://ine.es/ipc" in page and f'id="{r.slug}"' in page
    story = client.get(f"/historia/{st.id}").text
    assert "Esta afirmación se repite en otros medios" in story and "/repetidas" in story


def test_empty_page(engine):
    from fastapi.testclient import TestClient

    from truthnews.config import Settings
    from truthnews.web.app import create_app

    page = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine)).get("/repetidas").text
    assert "Aún no hay afirmaciones repetidas" in page
