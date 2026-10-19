from datetime import timedelta
from types import SimpleNamespace as NS

from truthnews.analysis.timeliness import MIN_STORIES, by_outlet, load, timings
from truthnews.models import Article, Claim, Evidence, Outlet, Story, Verification, utcnow

T0 = utcnow()


def c(story, outlet, hours, verdict, cid=0):
    return NS(
        id=cid,
        story_id=story,
        outlet=NS(name=outlet),
        article=NS(published_at=T0 + timedelta(hours=hours)),
        verification=NS(verdict=verdict),
    )


def test_timings_first_right_and_first_wrong():
    claims = [
        c(1, "A", 3, "verdadero"),
        c(1, "B", 1, "falso"),
        c(1, "B", 5, "verdadero"),
        c(1, "C", 2, "sin-datos"),  # sin dato: no cuenta
        c(2, "A", 1, "impreciso"),
        c(None, "A", 0, "verdadero"),  # sin historia
        NS(id=9, story_id=2, outlet=NS(name="D"), article=None, verification=None),
    ]
    (s1, s2) = timings(claims, {1: T0, 2: T0})
    assert [(o.outlet, o.right_after_h, o.first_wrong) for o in s1.outlets] == [
        ("A", 3.0, False),
        ("B", 5.0, True),
    ]
    assert s1.first_right.outlet == "A"
    assert s2.first_right is None and s2.outlets[0].first_wrong


def test_story_without_articles_starts_at_its_first_claim():
    # Produccion 2026-10-19: /historia/1912 daba 500 (KeyError) porque sus articulos estaban en otra historia.
    (st,) = timings([c(7, "A", 2, "verdadero"), c(7, "B", 4, "falso")], {})
    assert st.start == T0 + timedelta(hours=2)
    assert [(o.outlet, o.right_after_h) for o in st.outlets] == [("A", 0.0), ("B", None)]


def test_by_outlet_needs_a_sample():
    stories = []
    for i in range(MIN_STORIES):
        stories.append(c(i, "A", 2, "verdadero"))
        stories.append(c(i, "B", 1, "verdadero" if i % 2 else "falso"))
    stories.append(c(99, "C", 1, "verdadero"))
    ranked, few = by_outlet(timings(stories, {i: T0 for i in [*range(MIN_STORIES), 99]}))
    assert [r.outlet for r in ranked] == ["A", "B"]  # A acierta 5/5; B 2/5
    assert ranked[0].median_h == 2.0 and ranked[1].first_wrong == 3
    assert [r.outlet for r in few] == ["C"] and not few[0].ranked


def _db(session, n_stories):
    now = utcnow()
    outs = {}
    for slug in ("rapido", "lento"):
        o = Outlet(
            slug=slug, name=slug.title(), homepage="https://x", country="ES", language="es", scope="national"
        )
        session.add(o)
        outs[slug] = o
    session.flush()
    sid = None
    for i in range(n_stories):
        st = Story(
            title=f"Paro {i}",
            category="economia",
            country="ES",
            first_seen=now,
            last_seen=now,
            n_articles=2,
            n_outlets=2,
        )
        session.add(st)
        session.flush()
        sid = st.id
        for slug, hours, verdict in (("rapido", 1, "verdadero"), ("lento", 6, "falso")):
            a = Article(
                outlet_id=outs[slug].id,
                url=f"https://x/{i}/{slug}",
                url_hash=f"{i}{slug}".ljust(64, "_"),
                title=f"Paro {i}",
                published_at=now + timedelta(hours=hours),
                language="es",
                country="ES",
                category="economia",
                topics=[],
                story_id=st.id,
            )
            session.add(a)
            session.flush()
            cl = Claim(
                article_id=a.id,
                story_id=st.id,
                outlet_id=outs[slug].id,
                text="El paro es del 10 %",
                indicator="paro",
                geo="ES",
                value=10.0,
                unit="pct",
            )
            session.add(cl)
            session.flush()
            v = Verification(claim_id=cl.id, verdict=verdict, confidence=0.9, explanation="x", method="n")
            v.evidence.append(
                Evidence(source="ine", label="Paro", url="https://ine.es", period="T3", value=10.0)
            )
            session.add(v)
    session.commit()
    return sid


def test_load_and_pages(engine, session):
    from fastapi.testclient import TestClient

    from truthnews.config import Settings
    from truthnews.web.app import create_app

    sid = _db(session, MIN_STORIES)
    ts = load(session)
    assert (
        len(ts) == MIN_STORIES
        and ts[0].first_right.outlet == "Rapido"
        and ts[0].first_right.right_after_h == 0.0
    )
    assert len(load(session, sid)) == 1
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    medios = client.get("/medios").text
    assert "Quién informa primero y bien" in medios and "<b>5</b>/5" in medios and "0.0 h" in medios
    page = client.get(f"/historia/{sid}").text
    assert "Primero con la cifra correcta: Rapido, 0.0 h" in page


def test_empty_table(engine):
    from fastapi.testclient import TestClient

    from truthnews.config import Settings
    from truthnews.web.app import create_app

    medios = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine)).get("/medios").text
    assert "Aún ningún medio tiene 5 historias con dato oficial comprobado." in medios
