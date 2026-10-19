from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from truthnews.ai import statements
from truthnews.ai.client import AIClient, AIResult
from truthnews.config import Settings
from truthnews.models import PoliticalStatement, Story
from truthnews.registry import ActorSpec, ChannelSpec
from truthnews.web.app import create_app

NOW = datetime.now(UTC)


class FakeAI(AIClient):
    def __init__(self, data):
        self.data, self.model, self.users = data, "claude-opus-5-5", []

    def structured(self, system, user, schema):
        self.users.append(user)
        return AIResult(data=self.data, model=self.model)


def _setup(session):
    st = Story(
        title="Desalojo en Ceuta",
        category="politica",
        country="ES",
        first_seen=NOW,
        last_seen=NOW,
        n_outlets=3,
    )
    old = Story(
        title="Vieja",
        category="politica",
        country="ES",
        first_seen=NOW,
        last_seen=NOW - timedelta(days=5),
        n_outlets=3,
    )
    session.add_all([st, old])
    session.flush()
    rows = []
    for i, (actor, text) in enumerate(
        [("sumar", "Comunicado sobre Ceuta"), ("pp", "Mando unico en Ceuta"), ("bng", "Galiza")]
    ):
        r = PoliticalStatement(
            actor=actor,
            country="ES",
            channel="web",
            url=f"https://p.test/{i}",
            url_hash=f"{i}".ljust(64, "0"),
            text=text,
            published_at=NOW - timedelta(minutes=i),
            fetched_at=NOW,
        )
        session.add(r)
        rows.append(r)
    session.commit()
    return st, old, rows


def test_ai_links_are_validated_by_code(session):
    st, old, (a, b, c) = _setup(session)
    ai = FakeAI(
        {
            "links": [
                {"statement": a.id, "story": st.id},
                {"statement": b.id, "story": st.id},
                {"statement": c.id, "story": None},
                {"statement": 999, "story": st.id},  # declaracion inventada
                {"statement": c.id, "story": old.id},  # historia fuera de la lista
                {"statement": a.id, "story": old.id},  # repetida
            ]
        }
    )
    assert statements.run(session, ai, "ES") == {"statements": 3, "linked": 2}
    assert a.story_id == st.id and b.story_id == st.id and c.story_id is None
    historias = ai.users[0].split("\n\nDECLARACIONES")[0].splitlines()
    assert f"{old.id}\tVieja" not in historias and "Comunicado sobre Ceuta" in ai.users[0]
    # ya enlazadas no se vuelven a mandar; fuera de las 3 h primeras tampoco
    c.fetched_at = NOW - timedelta(hours=4)
    session.commit()
    assert statements.run(session, FakeAI({"links": []}), "ES") == {"statements": 0, "linked": 0}


def test_block_is_symmetric_alphabetical_and_hidden_without_links(engine, session):
    st, _, (a, b, _c) = _setup(session)
    actors = [
        ActorSpec("bng", "BNG", "Bloque", "h", "ES", None, (ChannelSpec("web", url="u"),)),
        ActorSpec("pp", "PP", "Partido Popular", "h", "ES", None, (ChannelSpec("web", url="u"),)),
        ActorSpec("psoe", "PSOE", "Partido Socialista", "h", "ES", "sin canal", ()),
        ActorSpec("sumar", "Sumar", "Movimiento Sumar", "h", "ES", None, (ChannelSpec("web", url="u"),)),
        ActorSpec("x", "X", "Otro pais", "h", "PT", None, (ChannelSpec("web", url="u"),)),
    ]
    assert statements.for_story(session, st, actors) == []
    a.story_id = b.story_id = st.id
    session.commit()
    rows = statements.for_story(session, st, actors)
    assert [r["actor"].slug for r in rows] == ["bng", "pp", "psoe", "sumar"]
    assert [len(r["statements"]) for r in rows] == [0, 1, 0, 1]
    page = (
        TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
        .get(f"/historia/{st.id}")
        .text
    )
    assert (
        "Qué dicen los partidos" in page
        and "«Comunicado sobre Ceuta»" in page
        and "«Mando unico en Ceuta»" in page
    )
    assert "Sin declaración enlazada en sus canales verificados." in page  # BNG, mismo formato
    assert "Sin canal oficial verificado todavía." in page  # PSOE en el registro real


def test_nothing_to_link(session):
    assert statements.run(session, FakeAI({"links": []}), "ES") == {"statements": 0, "linked": 0}
