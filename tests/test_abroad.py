from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from truthnews.analysis import abroad
from truthnews.analysis.cluster import Doc
from truthnews.config import Settings
from truthnews.models import Article, ArticleTranslation, Outlet, Story, StoryAbroad
from truthnews.web.app import create_app

NOW = datetime.now(UTC)


def test_match_threshold_and_caps():
    stories = {
        1: ["Ucrania lanza su mayor ataque con drones sobre San Petersburgo"],
        2: ["Huelga de metro en Madrid"],
    }
    cands = [
        (Doc(key="a", title="Ucrania ataca San Petersburgo con drones"), "MX"),
        (Doc(key="b", title="Gran ataque con drones de Ucrania sobre San Petersburgo"), "MX"),
        (Doc(key="c", title="Ataque de drones ucranianos sobre San Petersburgo"), "MX"),
        (Doc(key="d", title="Ucrania y los drones sobre San Petersburgo"), "MX"),
        (Doc(key="e", title="El Real Madrid gana la liga"), "AR"),
    ]
    out = abroad.match(stories, cands, threshold=0.3, per_country=3)
    assert 2 not in out
    assert len(out[1]) == 3 and all(k != "e" for k, _ in out[1])  # tope por pais
    sims = [s for _, s in out[1]]
    assert sims == sorted(sims, reverse=True)
    assert abroad.match(stories, cands, threshold=0.99) == {}
    assert len(abroad.match(stories, cands, threshold=0.3, per_story=1, per_country=9)[1]) == 1


def _outlet(session, slug, country, lang):
    o = Outlet(
        slug=slug,
        name=slug.upper(),
        homepage=f"https://{slug}.x",
        country=country,
        language=lang,
        scope="national",
    )
    session.add(o)
    session.flush()
    return o


def _art(session, o, title, story=None, minutes=0):
    a = Article(
        outlet_id=o.id,
        url=f"https://{o.slug}.x/{abs(hash(title))}",
        url_hash=f"{o.slug}{abs(hash(title))}".ljust(64, "0")[:64],
        title=title,
        published_at=NOW - timedelta(minutes=minutes),
        language=o.language,
        country=o.country,
        category="internacional",
        story_id=story.id if story else None,
    )
    session.add(a)
    session.flush()
    return a


def test_link_uses_spanish_or_translation_and_replaces_each_cycle(engine, session):
    st = Story(
        title="Drones", category="internacional", country="ES", first_seen=NOW, last_seen=NOW, n_outlets=2
    )
    solo = Story(
        title="Solo", category="internacional", country="ES", first_seen=NOW, last_seen=NOW, n_outlets=1
    )
    session.add_all([st, solo])
    session.flush()
    es1, es2 = _outlet(session, "es1", "ES", "es"), _outlet(session, "es2", "ES", "es")
    mx, de, fr = (
        _outlet(session, "mx1", "MX", "es"),
        _outlet(session, "de1", "DE", "de"),
        _outlet(session, "fr1", "FR", "fr"),
    )
    _art(session, es1, "Ucrania lanza su mayor ataque con drones sobre San Petersburgo", st)
    _art(session, es2, "Mayor ataque de drones de Ucrania sobre San Petersburgo", st)
    a_mx = _art(session, mx, "Ucrania ataca San Petersburgo con su mayor oleada de drones")
    a_de = _art(session, de, "Größter ukrainischer Drohnenangriff auf Sankt Petersburg")
    _art(session, fr, "Attaque de drones ukrainiens sur Saint-Pétersbourg")  # sin traduccion: no se enlaza
    _art(session, mx, "Ucrania lanza drones sobre San Petersburgo", minutes=60 * 24 * 5)  # fuera de ventana
    session.add(
        ArticleTranslation(
            article_id=a_de.id,
            lang="es",
            title="Mayor ataque ucraniano con drones sobre San Petersburgo",
            model="m",
        )
    )
    session.commit()

    out = abroad.link(session, "ES", "es")
    assert out["stories"] == 1 and out["links"] == 2
    assert {a.id for a in abroad.for_story(session, st.id)} == {a_mx.id, a_de.id}
    abroad.link(session, "ES", "es")  # recalcular no duplica
    assert len(session.scalars(select(StoryAbroad)).all()) == 2
    assert abroad.link(session, "PT", "pt") == {"stories": 0, "links": 0}
    session.commit()

    page = (
        TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
        .get(f"/historia/{st.id}")
        .text
    )
    assert "Cómo lo cuentan en otros países" in page and "México" in page and "Alemania" in page
    assert (
        "Größter ukrainischer Drohnenangriff" in page
        and "traducción automática con IA del original (de)" in page
    )


def test_centroid_of_nothing_is_empty():
    assert abroad.centroid([]) == {}


def test_serial_content_like_horoscopes_is_not_linked(session):
    st = Story(
        title="Horóscopo de Cáncer hoy, 20 de octubre",
        category="sociedad",
        country="ES",
        first_seen=NOW,
        last_seen=NOW,
        n_outlets=2,
    )
    session.add(st)
    session.flush()
    es1, es2 = _outlet(session, "h1", "ES", "es"), _outlet(session, "h2", "ES", "es")
    ar = _outlet(session, "h3", "AR", "es")
    _art(session, es1, "Horóscopo de Cáncer hoy, 20 de octubre", st)
    _art(session, es2, "Horóscopo de Cáncer para hoy, 20 de octubre", st)
    _art(session, ar, "Horóscopo Cáncer de hoy, 19 de octubre")
    session.commit()
    assert abroad.link(session, "ES", "es")["links"] == 0
