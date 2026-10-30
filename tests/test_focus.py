from datetime import UTC, datetime, timedelta

import pytest

from truthnews.ai import cost
from truthnews.ai import threads as threads_mod
from truthnews.focus import Focus, ensure_investigation
from truthnews.investigate import process_pending
from truthnews.models import Article, CrawlRun, Investigation, Outlet, Story, Topic, utcnow

NOW = datetime.now(UTC)
Q = "¿Que se sabe del choque de trenes entre un AVE y un Iryo en Toledo?"


def _world(session):
    outs = []
    for i in range(3):
        o = Outlet(
            slug=f"f{i}",
            name=f"F{i}",
            homepage="https://f",
            country="ES",
            language="es",
            scope="national",
        )
        session.add(o)
        outs.append(o)
    session.flush()
    stories = []
    for title in ("Un AVE embiste a un Iryo cerca de Los Yébenes", "El Gobierno aprueba los presupuestos"):
        st = Story(
            title=title,
            category="sociedad",
            country="ES",
            first_seen=NOW,
            last_seen=NOW,
            n_articles=3,
            n_outlets=3,
        )
        session.add(st)
        session.flush()
        for i, o in enumerate(outs):
            session.add(
                Article(
                    outlet_id=o.id,
                    url=f"https://f/{st.id}/{i}",
                    url_hash=f"{st.id}-{i}",
                    title=title,
                    language="es",
                    country="ES",
                    category="sociedad",
                    published_at=NOW,
                    story_id=st.id,
                )
            )
        stories.append(st)
    session.flush()
    return stories


def test_off_without_terms():
    assert not Focus(())
    assert not Focus(["  ", ""])


def test_matches_whole_words_without_accents():
    f = Focus(["iryo", "Los Yebenes", "alta velocidad"])
    assert f.matches("Un AVE embiste a un IRYO")
    assert f.matches("Choque cerca de Los Yébenes")
    assert not f.matches("Iryoxx no es la empresa")
    assert not f.matches("velocidad alta")


def test_focus_picks_its_stories_and_topics(session):
    accident, budget = _world(session)
    f = Focus(["iryo", "adif"])
    assert f.stories(session, "ES") == [accident]
    t1 = Topic(title="Choque ferroviario", category="sociedad", country="ES", first_seen=NOW, last_seen=NOW)
    t2 = Topic(title="Cuentas publicas", category="economia", country="ES", first_seen=NOW, last_seen=NOW)
    session.add_all([t1, t2])
    session.flush()
    accident.topic_id, budget.topic_id = t1.id, t2.id
    session.flush()
    session.expire_all()
    assert [t.id for t in f.topics(session, "ES")] == [t1.id]


def test_focus_pool_is_apart_from_the_general_budget():
    m = cost.Meter(spent_before=10, daily_budget=10, focus_budget=5)
    with pytest.raises(cost.BudgetExceeded):
        m.check()
    m.check(cost.FOCUS)  # la general esta agotada; el foco sigue
    m.charge("claude-opus-5-5", {"output_tokens": 300_000}, cost.FOCUS)  # 6 USD
    assert m.focus_spent == pytest.approx(6) and m.summary()["hoy_usd"] == pytest.approx(10)
    with pytest.raises(cost.BudgetExceeded, match="del foco"):
        m.check(cost.FOCUS)
    # Sin bolsa propia, el foco gasta de la general, como cualquier otra llamada.
    assert not cost.Meter(focus_budget=0)._own_pool(cost.FOCUS)


def test_worker_reads_focus_spend_apart(session):
    from truthnews.worker import focus_spent_today, spent_today

    session.add(
        CrawlRun(started_at=NOW, stats={"ai_cost": {"usd": 3, "verificacion_usd": 0.5, "foco_usd": 2}})
    )
    session.flush()
    assert spent_today(session, NOW) == pytest.approx((0.5, 0.5))
    assert focus_spent_today(session, NOW) == pytest.approx(2)


def test_focus_investigation_is_created_and_reopened(session):
    refresh = timedelta(minutes=30)
    assert ensure_investigation(session, Q, "ES", refresh) == "creada"
    assert ensure_investigation(session, Q, "ES", refresh) == "pendiente"
    inv = session.query(Investigation).one()
    inv.status, inv.updated_at = "publicada", utcnow() - timedelta(minutes=10)
    assert ensure_investigation(session, Q, "ES", refresh) == "publicada"
    inv.updated_at = utcnow() - timedelta(minutes=31)
    assert ensure_investigation(session, Q, "ES", refresh) == "reabierta"
    assert inv.status == "pendiente"
    assert ensure_investigation(session, "corta", "ES", refresh) == "sin pregunta"


def test_process_pending_can_take_only_the_focus_question(session):
    session.add_all([Investigation(question="¿Otra pregunta cualquiera?"), Investigation(question=Q)])
    session.flush()
    out = process_pending(session, ai=None, timeline=lambda q, s: [], question=Q)
    assert out == {"processed": 1, "failed": 0}
    statuses = {i.question: i.status for i in session.query(Investigation)}
    assert statuses == {Q: "publicada", "¿Otra pregunta cualquiera?": "pendiente"}


def test_threads_run_takes_the_given_stories(session, monkeypatch):
    accident, budget = _world(session)
    built = []

    class Done:
        status = "publicada"
        id = 1

    monkeypatch.setattr(threads_mod, "build_thread", lambda s, st, ai, **k: built.append(st.id) or Done())
    monkeypatch.setattr(threads_mod, "write_thread_piece", lambda s, t, ai: None)
    out = threads_mod.run(session, None, "ES", 2, stories=[accident], refresh=timedelta(minutes=30))
    assert built == [accident.id] and out["threads"] == 1


def test_focus_pieces_use_their_own_quota_and_cadence(session, monkeypatch):
    from truthnews.ai import pipeline as ai_pipeline
    from truthnews.config import Settings

    accident, _ = _world(session)
    t = Topic(title="Choque ferroviario", category="sociedad", country="ES", first_seen=NOW, last_seen=NOW)
    session.add(t)
    session.flush()
    accident.topic_id = t.id
    session.flush()
    calls = []
    monkeypatch.setattr(
        ai_pipeline,
        "write_batch",
        lambda s, ai, topics, v, n, c, r: calls.append((topics, n, r)) or (1, 0, 0),
    )
    off = Settings(database_url="sqlite://", ai_focus=())
    assert ai_pipeline._focus_pieces(session, off, object(), object()) == {} and not calls
    on = Settings(
        database_url="sqlite://", ai_focus=("iryo",), ai_focus_max_pieces=2, ai_focus_refresh_minutes=15
    )
    out = ai_pipeline._focus_pieces(session, on, object(), object())
    ((topics, n, refresh),) = calls
    assert [x.id for x in topics] == [t.id] and n == 2 and refresh == timedelta(minutes=15)
    assert out == {"focus_topics": 1, "focus_pieces": 1, "focus_in_revision": 0}


def test_focus_investigation_gets_the_dossier_of_its_stories_only(session):
    accident, budget = _world(session)
    session.add(Investigation(question=Q))
    session.flush()
    process_pending(session, ai=None, timeline=lambda q, s: [], question=Q, stories=[accident])
    r = session.query(Investigation).one().report
    assert [h["id"] for h in r["historias"]] == [accident.id] and r["datos"] == []
    (brief,) = r["dossier"]
    assert brief["titular"] == accident.title and len(brief["medios"]) == 3
    assert "foco" in r["metodo"]


def test_a_cut_cycle_still_counts_its_ai_spend(session, engine):
    """Decision del usuario 2026-10-30 (tope de 2 EUR al dia): el gasto se guarda tras cada paso que gasta,
    asi que un ciclo cortado por un redespliegue tambien cuenta para el tope del siguiente ciclo."""
    from truthnews import worker

    run = CrawlRun(started_at=NOW, stats={})
    session.add(run)
    session.commit()
    meter = cost.start_cycle(0, 1.5)
    summary = worker._Timed()
    summary.persist = lambda: worker._save_cost(engine, run.id, summary)
    summary["run"] = run.id
    meter.charge("claude-opus-5-5", {"output_tokens": 50_000})  # 1 USD
    summary["threads"] = {}
    # El ciclo se corta aqui (redespliegue): no llega al guardado final.
    session.expire_all()
    assert worker.spent_today(session, NOW)[0] == pytest.approx(1.0)
    cost.start_cycle(0, 0)
