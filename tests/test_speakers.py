"""Quien dice la verdad: historial de veredictos por partido y por persona (mismo metodo que los medios)."""

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from truthnews.analysis import speakers
from truthnews.config import Settings
from truthnews.models import Article, Claim, Entity, Outlet, Verification
from truthnews.web.app import create_app


def seed(session):
    o = Outlet(slug="m", name="Medio", homepage="https://m.es", country="ES", language="es", scope="nacional")
    party = Entity(key="partido:ejemplo", kind="partido", name="Partido Ejemplo", country="ES")
    person = Entity(key="persona:ana lopez", kind="persona", name="Ana López", country="ES")
    quiet = Entity(key="persona:sin datos", kind="persona", name="Sin Datos", country="ES")
    place = Entity(key="lugar:madrid", kind="lugar", name="Madrid", country="ES")
    session.add_all([o, party, person, quiet, place])
    session.flush()
    a = Article(
        outlet_id=o.id,
        url="https://m.es/1",
        url_hash="s" * 64,
        title="Declaraciones con cifras",
        published_at=datetime(2026, 10, 18, tzinfo=UTC),
        language="es",
        country="ES",
        category="politica",
        topics=[],
    )
    session.add(a)
    session.flush()
    plan = [(party, "verdadero")] * 5 + [(party, "falso")]
    plan += [(person, "verdadero"), (person, "enganoso"), (quiet, "sin-datos"), (place, "verdadero")]
    for i, (ent, verdict) in enumerate(plan):
        c = Claim(
            article_id=a.id,
            outlet_id=o.id,
            text=f"Afirmacion {i}",
            indicator="paro",
            geo="ES",
            value=float(i),
            unit="pct",
            speaker_entity_id=ent.id,
        )
        session.add(c)
        session.flush()
        session.add(
            Verification(claim_id=c.id, verdict=verdict, confidence=0.8, explanation="x", method="nivel")
        )
    session.commit()
    return party, person


def test_records_and_ranking_use_wilson_and_minimum(session):
    party, person = seed(session)
    recs = speakers.records(session)
    assert {r.entity.name for r in recs} == {"Partido Ejemplo", "Ana López", "Sin Datos"}  # sin lugares
    ranked, few = speakers.ranking(recs)
    assert [r.entity.name for r in ranked] == ["Partido Ejemplo"]
    p = ranked[0]
    assert (p.right, p.checked) == (5, 6) and round(p.accuracy, 2) == 0.83 and 0.4 < p.lower < 0.83
    assert [r.entity.name for r in few] == ["Ana López"]  # "Sin Datos": 0 comprobadas, no aparece
    assert [r.entity.name for r in speakers.records(session, kind="partido")] == ["Partido Ejemplo"]
    assert len(speakers.history(session, person.id)) == 2


def test_speakers_page(engine, session):
    seed(session)
    tc = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    page = tc.get("/quien-dice-la-verdad").text
    assert "Quién dice la verdad" in page and "Partidos" in page and "Personas" in page
    assert "Partido Ejemplo" in page and "83 %" in page and "5/6" in page
    assert "Con pocas verificaciones todavía (1)" in page and "Ana López" in page
    assert "Sin Datos" not in page and "Madrid" not in page
    assert "No deducimos la afiliación de nadie" in page
    assert 'href="/quien-dice-la-verdad"' in page
    assert "/quien-dice-la-verdad" in tc.get("/sitemaps/paginas-1.xml").text
    assert "Who tells the truth" in tc.get("/quien-dice-la-verdad?lang=en").text


def test_empty_page_says_so(engine):
    tc = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    assert "Aún nadie tiene 5 afirmaciones comprobadas" in tc.get("/quien-dice-la-verdad").text
