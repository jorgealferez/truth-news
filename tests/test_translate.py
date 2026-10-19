from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from truthnews.ai import pipeline as ai_pipeline
from truthnews.ai import translate
from truthnews.ai.client import AIClient, AIError, AIResult
from truthnews.config import Settings
from truthnews.models import Article, ArticleTranslation, Outlet, Story
from truthnews.web.app import create_app

NOW = datetime.now(UTC)


class FakeAI(AIClient):
    def __init__(self, responses):
        self.responses = list(responses)
        self.model = "claude-opus-5-5"
        self.users = []

    def structured(self, system, user, schema):
        self.users.append(user)
        r = self.responses.pop(0)
        if isinstance(r, Exception):
            raise r
        if callable(r):
            r = r(user)
        return AIResult(data=r, model=self.model)


def echo(user):
    """Traduce cada linea 'id\\t[lang] titular' a 'ES: titular'."""
    rows = [line.split("\t", 1) for line in user.splitlines()[2:]]
    return {"items": [{"id": int(i), "title": "ES: " + t.split("] ", 1)[1]} for i, t in rows]}


@pytest.fixture()
def story(session):
    st = Story(title="Cumbre", category="internacional", country="ES", first_seen=NOW, last_seen=NOW)
    old = Story(
        title="Vieja",
        category="internacional",
        country="ES",
        first_seen=NOW,
        last_seen=NOW - timedelta(days=5),
    )
    session.add_all([st, old])
    session.flush()
    outlets = []
    for slug, lang in [("es1", "es"), ("de1", "de"), ("ar1", "ar"), ("fr1", "fr")]:
        o = Outlet(
            slug=slug,
            name=slug.upper(),
            homepage=f"https://{slug}.x",
            country="XX",
            language=lang,
            scope="international",
        )
        session.add(o)
        outlets.append(o)
    session.flush()
    for i, o in enumerate(outlets):
        for s in (st, old):
            session.add(
                Article(
                    outlet_id=o.id,
                    url=f"https://{o.slug}.x/{s.title}",
                    url_hash=f"{o.slug}{s.title}".ljust(64, "0"),
                    title=f"Titular {o.slug}",
                    published_at=NOW - timedelta(minutes=i),
                    language=o.language,
                    country="XX",
                    category="internacional",
                    story_id=s.id,
                )
            )
    session.commit()
    return st


def test_pending_only_recent_foreign_untranslated(session, story):
    rows = translate.pending(session, "es", 10)
    assert {a.title for a in rows} == {"Titular de1", "Titular ar1", "Titular fr1"}
    assert all(a.story_id == story.id for a in rows)


def test_run_translates_respects_budget_and_discards_invented_ids(session, story):
    def with_fake_id(user):
        data = echo(user)
        data["items"].append({"id": 99999, "title": "inventado"})
        data["items"].append({"id": data["items"][0]["id"], "title": "repetido"})
        return data

    ai = FakeAI([with_fake_id])
    assert translate.run(session, ai, ["es"], max_per_cycle=2) == {"es": 2}
    rows = session.scalars(select(ArticleTranslation)).all()
    assert len(rows) == 2 and all(r.title.startswith("ES: ") and r.model == "claude-opus-5-5" for r in rows)
    assert "Idioma de destino: espanol (es)" in ai.users[0]
    # el siguiente ciclo traduce solo lo que falta y el original no se toca
    assert translate.run(session, FakeAI([echo]), ["es"], max_per_cycle=10) == {"es": 1}
    assert translate.run(session, FakeAI([]), ["es"], max_per_cycle=10) == {"es": 0}
    assert {a.title for a in session.scalars(select(Article))} >= {"Titular de1", "Titular ar1"}
    ids = [a.id for a in translate.pending(session, "en", 10)]
    assert translate.titles(session, ids, "es") and translate.titles(session, [], "es") == {}


def test_empty_answer_stops_without_looping(session, story):
    assert translate.run(session, FakeAI([{"items": []}]), ["es"], max_per_cycle=100) == {"es": 0}


def test_one_translation_per_article_and_language(session, story):
    art = translate.pending(session, "es", 1)[0]
    session.add(ArticleTranslation(article_id=art.id, lang="es", title="a", model="m"))
    session.add(ArticleTranslation(article_id=art.id, lang="es", title="b", model="m"))
    with pytest.raises(IntegrityError):
        session.flush()
    session.rollback()


def test_pipeline_translates_first_and_survives_ai_errors(session, story):
    settings = Settings(database_url="sqlite://", default_country="ZZ")
    out = ai_pipeline.run(session, settings, ai=FakeAI([{"temas": []}]), translator=FakeAI([AIError("x")]))
    assert "translations" not in out and "topics" in out
    out = ai_pipeline.run(session, settings, ai=FakeAI([{"temas": []}]), translator=FakeAI([echo, echo]))
    assert out["translations"] == {"es": 3, "en": 4}  # luego el ingles, con su propio tope


def test_story_shows_translation_marked_under_original(engine, session, story):
    translate.run(session, FakeAI([echo]), ["es"], max_per_cycle=10)
    page = (
        TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
        .get(f"/historia/{story.id}")
        .text
    )
    assert "Titular de1" in page and "ES: Titular de1" in page
    assert "traducción automática con IA del original (de)" in page
    assert "ES: Titular es1" not in page  # lo que ya esta en espanol no se traduce


def test_english_reader_sees_headline_translated_under_h1(engine, session, story):
    story.title = "Titular es1"
    session.commit()

    def to_en(user):
        rows = [line.split("\t", 1) for line in user.splitlines()[2:]]
        return {"items": [{"id": int(i), "title": "EN: " + t.split("] ", 1)[1]} for i, t in rows]}

    assert translate.run(session, FakeAI([to_en]), ["en"], max_per_cycle=10) == {"en": 4}
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    page = client.get(f"/historia/{story.id}?lang=en").text
    h1 = page.split("<h1>", 1)[1].split("</section>", 1)[0]
    assert "EN: Titular es1" in h1 and "AI machine translation of the original (es)" in h1
    fresh = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    assert "EN: Titular es1" not in fresh.get(f"/historia/{story.id}").text  # en espanol no se muestra
