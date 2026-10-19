"""Declaraciones de los partidos juzgadas con el juez de siempre y guardadas aparte (ADR 0031)."""

import hashlib
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from tests.test_ai import FakeAI
from truthnews import registry
from truthnews.ai import claims as ai_claims
from truthnews.ai.client import AIError
from truthnews.analysis import speakers, statement_checks
from truthnews.analysis.verify import METHOD_VERSION, Observation, Verifier
from truthnews.config import Settings
from truthnews.models import CrawlRun, Entity, PoliticalStatement, StatementCheck
from truthnews.web.app import create_app

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
Y = NOW.year
TEXT = "El paro se sitúa en el 10,6 % según los últimos datos."


def verifier(value=10.6):
    def fetch(source, geo, label):
        hist = {f"{Y}-08": 10.4, f"{Y}-09": value}
        return Observation("eurostat", label, "https://ec.europa.eu/x", f"{Y}-09", value, history=hist)

    return Verifier(fetch)


def actors():
    ch = (registry.ChannelSpec(channel="web", url="https://ejemplo.es/noticias"),)
    return [
        registry.ActorSpec("ejemplo", "Ejemplo", "Partido Ejemplo", "https://ejemplo.es", "ES", channels=ch),
        registry.ActorSpec("mudo", "Mudo", "Partido Mudo", "https://mudo.es", "ES"),
        registry.ActorSpec("lejos", "Lejos", "Partido Lejos", "https://lejos.fr", "FR"),
    ]


def statement(session, actor, text, hours_ago, channel="web", summary=None):
    url = f"https://{actor}.es/{channel}/{hours_ago}"
    st = PoliticalStatement(
        actor=actor,
        country="ES",
        channel=channel,
        url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        text=text,
        summary=summary,
        published_at=NOW - timedelta(hours=hours_ago),
    )
    session.add(st)
    session.flush()
    return st


def party(session):
    ent = Entity(
        key="partido:ejemplo", kind="partido", name="Ejemplo", aliases=["Partido Ejemplo"], country="ES"
    )
    session.add(ent)
    session.flush()
    return ent


def test_judges_statement_and_attributes_to_party(session):
    ent = party(session)
    st = statement(session, "ejemplo", "corto", 2, summary=TEXT)  # se juzga el resumen, mas largo
    stats = statement_checks.run(session, verifier(), now=NOW, actors=actors())
    assert stats["statements"] == 1 and stats["claims"] == 1
    check = session.query(StatementCheck).one()
    assert check.statement_id == st.id and check.speaker_entity_id == ent.id
    assert check.indicator == "paro" and check.verdict == "verdadero"
    assert check.method.endswith(f"/{METHOD_VERSION}") and check.evidence[0]["source"] == "eurostat"
    # ya juzgada: el siguiente ciclo no la repite
    assert statement_checks.run(session, verifier(), now=NOW, actors=actors())["claims"] == 0


def test_same_message_on_two_channels_is_judged_once(session):
    party(session)
    statement(session, "ejemplo", TEXT, 3, channel="web")
    statement(session, "ejemplo", TEXT.upper(), 2, channel="mastodon")
    statement(session, "ejemplo", TEXT, 40, channel="bluesky")  # dias despues no es duplicado
    stats = statement_checks.run(session, verifier(), now=NOW, actors=actors())
    assert stats["duplicates"] == 1 and stats["statements"] == 2


def test_old_window_empty_and_unknown_party(session):
    statement(session, "ejemplo", TEXT, 24 * 40)  # fuera de la ventana
    statement(session, "ejemplo", "Sin cifras que comprobar.", 1)
    statement(session, "otro", TEXT, 1)  # sin entidad: se guarda igual, sin atribuir
    statement(session, "ejemplo", "", 5)
    stats = statement_checks.run(session, verifier(), now=NOW, actors=actors())
    assert stats["claims"] == 1
    assert session.query(StatementCheck).one().speaker_entity_id is None


def test_rejudge_old_method_writes_the_correction(session):
    party(session)
    statement(session, "ejemplo", TEXT, 1)
    statement_checks.run(session, verifier(), now=NOW, actors=actors())
    check = session.query(StatementCheck).one()
    check.method, check.verdict = "nivel/v4", "falso"
    session.flush()
    stats = statement_checks.rejudge_outdated(session, verifier())
    assert stats == {"rejudged": 1, "changed": 1}
    assert check.verdict == "verdadero" and "Corregido: antes «falso»" in check.explanation
    assert statement_checks.rejudge_outdated(session, verifier()) == {"rejudged": 0, "changed": 0}


def test_without_channel_lists_parties_equally():
    assert statement_checks.without_channel(actors()) == ["Mudo"]
    assert statement_checks.without_channel(actors(), country="FR") == ["Lejos"]
    real = statement_checks.without_channel()  # registro real: lista ordenada, sin trato distinto
    assert real == sorted(real)


def test_records_mix_news_and_channels_and_page_says_so(engine, session):
    party(session)
    for h in range(5):
        statement(session, "ejemplo", TEXT.replace("10,6", f"10,{6 - h}"), 10 * h + 1)
    statement_checks.run(session, verifier(), now=NOW, actors=actors())
    session.commit()
    rec = speakers.records(session, kind="partido")[0]
    assert rec.checked == 5 and rec.own == 5 and rec.ranked
    client = TestClient(create_app(Settings(database_url=str(engine.url)), engine=engine))
    html = client.get("/quien-dice-la-verdad").text
    assert "5 de sus canales" in html and 'id="sin-canal"' in html


def ai_reply(*props):
    return {
        "afirmaciones": [
            {
                "id": i,
                "comprobable": True,
                "indicador": ind,
                "territorio": geo,
                "periodo": "",
                "valor": v,
                "sentido": "ninguno",
                "motivo": "",
            }
            for i, ind, geo, v in props
        ]
    }


def test_ai_judges_what_rules_miss_and_moves_the_cursor(session):

    ent = party(session)
    rules_miss = "Con nuestras medidas el paro baja hasta el 10,6 % este trimestre, el dato mas bajo."
    st = statement(session, "ejemplo", rules_miss, 2)
    statement(session, "ejemplo", "Un comunicado sin cifras.", 1)
    run = CrawlRun()
    session.add(run)
    session.flush()
    ai = FakeAI([ai_reply((0, "paro", "ES", 10.6))])
    out = statement_checks.run_ai(session, ai, run.id, verifier(), now=NOW, actors=actors())
    assert out["llamadas"] == 1 and out["frases_enviadas"] == 1 and out["claims"] == 1
    check = session.query(StatementCheck).one()
    assert check.extractor == "ia" and check.statement_id == st.id and check.speaker_entity_id == ent.id
    assert check.verdict == "verdadero"
    assert statement_checks.ai_cursor(session) == out["cursor"] >= st.id
    # Lo ya enviado no se repite: siguiente ciclo sin frases nuevas, sin llamada.
    again = statement_checks.run_ai(session, FakeAI([]), None, verifier(), now=NOW, actors=actors())
    assert again["frases_candidatas"] == 0 and again["claims"] == 0


def test_ai_unavailable_keeps_the_cursor(session):

    statement(session, "ejemplo", "El paro baja hasta el 10,6 % este trimestre segun nuestros datos.", 2)
    run = CrawlRun()
    session.add(run)
    session.flush()
    out = statement_checks.run_ai(session, FakeAI([AIError("caida")]), run.id, verifier(), now=NOW)
    assert out["claims"] == 0 and statement_checks.ai_cursor(session) == 0


def test_ai_respects_the_call_cap(session, monkeypatch):

    monkeypatch.setattr(ai_claims, "BATCH", 1)
    a = statement(session, "ejemplo", "El paro baja hasta el 10,6 % este trimestre segun nuestros datos.", 3)
    b = statement(session, "ejemplo", "La inflacion baja hasta el 2,1 % este mes segun nuestros datos.", 2)
    run = CrawlRun()
    session.add(run)
    session.flush()
    out = statement_checks.run_ai(
        session, FakeAI([{"afirmaciones": []}]), run.id, verifier(), max_calls=1, now=NOW
    )
    assert out["llamadas"] == 1 and out["cursor"] == a.id < b.id  # la segunda queda para el siguiente ciclo


def test_rules_judge_the_body_of_the_release(session):
    party(session)
    st = statement(session, "ejemplo", "Nota de prensa sobre empleo", 2, summary="Entradilla sin cifras.")
    assert statement_checks.run(session, verifier(), now=NOW, actors=actors())["claims"] == 0
    st.body, st.body_status, st.body_fetched_at = f"Introduccion. {TEXT}", "ok", NOW
    assert statement_checks._body(st).startswith("Nota de prensa sobre empleo. Introduccion.")
    out = statement_checks.run(session, verifier(), now=NOW, actors=actors())
    assert out["claims"] == 1 and session.query(StatementCheck).one().statement_id == st.id


def test_ai_resends_once_a_statement_whose_body_came_later(session):
    party(session)
    st = statement(session, "ejemplo", "Nota de prensa sobre empleo", 2)
    first = CrawlRun()
    session.add(first)
    session.flush()
    out = statement_checks.run_ai(session, FakeAI([]), first.id, verifier(), now=NOW, actors=actors())
    assert out["frases_candidatas"] == 0 and statement_checks.ai_cursor(session) == st.id
    # El cuerpo llega en el ciclo siguiente: la declaracion ya paso el cursor, pero se envia otra vez.
    body = "Con nuestras medidas el paro baja hasta el 10,6 % este trimestre, el dato mas bajo."
    st.body, st.body_status, st.body_fetched_at = body, "ok", NOW + timedelta(minutes=30)
    second = CrawlRun()
    session.add(second)
    session.flush()
    ai = FakeAI([ai_reply((0, "paro", "ES", 10.6))])
    out = statement_checks.run_ai(session, ai, second.id, verifier(), now=NOW, actors=actors())
    assert out["llamadas"] == 1 and out["claims"] == 1 and out["cursor"] == st.id
    assert statement_checks.ai_body_cursor(session) == NOW + timedelta(minutes=30)
    third = CrawlRun()
    session.add(third)
    session.flush()
    again = statement_checks.run_ai(session, FakeAI([]), third.id, verifier(), now=NOW, actors=actors())
    assert again["frases_candidatas"] == 0  # una sola vez
