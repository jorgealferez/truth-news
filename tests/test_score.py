from datetime import UTC, datetime, timedelta

from truthnews.analysis import pipeline
from truthnews.analysis.compare import Comparison, Figure
from truthnews.analysis.score import contrast_of, priority_of, score_stories
from truthnews.analysis.verify import Verifier
from truthnews.data import Observation
from truthnews.models import Article, Outlet, Story
from truthnews.web import queries

NOW = datetime.now(UTC)


def test_contrast_of_weights_what_differs():
    plain, summary = contrast_of(Comparison(outlets=["A", "B"]), {})
    assert plain == 0 and summary["disputas"] == []
    f = Figure("detenidos", 3, "", "A", NOW, "")
    comp = Comparison(outlets=["A", "B"], disputes={"detenidos": [f, f]}, omissions={"A": ["Madrid"]})
    score, summary = contrast_of(comp, {"falso": 1, "sin-datos": 4})
    assert score == 2 + 3 + 1 and summary["veredictos"] == {"falso": 1} and summary["omisiones"] == 1
    # Sin nada que marcar, ni muchos medios ni la tendencia alcanzan a una diferencia real.
    assert priority_of(0, 30, 10) < priority_of(1, 2, 0)


def _outlets(session, n=4):
    outs = [
        Outlet(
            slug=f"m{i}",
            name=f"Medio {i}",
            homepage="https://m",
            country="ES",
            language="es",
            scope="national",
        )
        for i in range(n)
    ]
    session.add_all(outs)
    session.flush()
    return outs


def _article(session, i, outlet, title, when, summary="", story=None):
    a = Article(
        outlet_id=outlet.id,
        url=f"https://m/{i}",
        url_hash=f"{i:064d}",
        title=title,
        summary=summary,
        published_at=when,
        language="es",
        country="ES",
        category="sucesos",
        topics=[],
        story_id=story.id if story else None,
    )
    session.add(a)
    return a


def test_disputed_story_outranks_bigger_flat_one(session):
    outs = _outlets(session)
    for i, o in enumerate(outs):
        _article(
            session,
            i,
            o,
            "El Gobierno presenta los presupuestos generales del Estado",
            NOW - timedelta(minutes=10 + i),
        )
    for i, o in enumerate(outs[:2]):
        n = ("tres", "doce")[i]
        _article(
            session,
            10 + i,
            o,
            f"Disturbios en Valencia tras el partido: {n} detenidos por la policia",
            NOW - timedelta(minutes=30 + i),
        )
    session.flush()
    since = NOW - timedelta(hours=1)
    out = pipeline.run(session, since, Verifier(lambda s, g, label: None))
    assert out["scores"] == {"scored": 2, "with_contrast": 1}
    top = queries.top_stories(session, country="ES")
    assert [s.n_outlets for s in top] == [2, 4]
    assert top[0].contrast["disputas"] == ["detenidos"] and top[1].contrast_score == 0


def test_old_story_with_contrast_is_relaunched_when_outlets_return(session):
    outs = _outlets(session)
    old_when = NOW - timedelta(days=5)
    old = Story(
        title="La inflacion de los alquileres en Madrid dispara las protestas vecinales",
        category="sociedad",
        country="ES",
        first_seen=old_when,
        last_seen=old_when,
        n_articles=2,
        n_outlets=2,
        contrast_score=5.0,
        priority=5.1,
    )
    session.add(old)
    session.flush()
    for i, o in enumerate(outs[:2]):
        _article(session, i, o, old.title, old_when, story=old)
    for i, o in enumerate(outs[2:]):
        _article(
            session,
            10 + i,
            o,
            "Nuevas protestas vecinales por la inflacion de los alquileres en Madrid",
            NOW - timedelta(minutes=5 + i),
        )
    _article(session, 20, outs[0], "Un terremoto sacude Japon", NOW)
    session.flush()
    out = pipeline.assign_stories(session)
    assert out["stories_relaunched"] == 1
    session.refresh(old)
    assert old.relaunched_at is not None and old.n_articles == 4 and old.n_outlets == 4
    assert old.first_seen.replace(tzinfo=UTC) <= old_when + timedelta(seconds=1)
    assert old in queries.top_stories(session, country="ES")


def test_new_data_on_old_story_relaunches_it(session):
    outs = _outlets(session, 2)
    when = NOW - timedelta(days=4)
    st = Story(
        title="Paro",
        category="economia",
        country="ES",
        first_seen=when,
        last_seen=when,
        n_articles=2,
        n_outlets=2,
    )
    session.add(st)
    session.flush()
    _article(session, 1, outs[0], "La tasa de paro se sitúa en el 12,5 %", when, story=st)
    _article(session, 2, outs[1], "El paro baja", when, story=st)
    session.flush()
    period = f"{NOW.year}-{NOW.month:02d}"
    verifier = Verifier(
        lambda s, g, label: Observation("eurostat", label, "https://ec.europa.eu/x", period, 12.5)
    )
    pipeline.verify_claims(session, NOW - timedelta(days=30), verifier)
    session.refresh(st)
    assert st.relaunched_at is not None
    assert queries.top_stories(session, country="ES") == [st]


def test_backfill_scores_recent_unscored_stories_only(session):
    outs = _outlets(session, 2)
    recent, ancient = NOW - timedelta(days=3), NOW - timedelta(days=10)
    stories = []
    for k, when in enumerate((recent, ancient)):
        st = Story(
            title=f"H{k}",
            category="sucesos",
            country="ES",
            first_seen=when,
            last_seen=when,
            n_outlets=2,
            updated_at=when,
        )
        session.add(st)
        session.flush()
        for i, o in enumerate(outs):
            n = ("dos", "nueve")[i]
            _article(session, 10 * k + i, o, f"Incendio en un almacen: {n} heridos", when, story=st)
        stories.append(st)
    session.flush()
    assert score_stories(session, since=NOW) == {"scored": 1, "with_contrast": 1}
    assert stories[0].contrast["disputas"] == ["heridos"] and stories[1].contrast is None
    assert score_stories(session, since=NOW) == {"scored": 0, "with_contrast": 0}
