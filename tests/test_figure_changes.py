import hashlib
from datetime import timedelta

from truthnews.analysis.figure_changes import (
    MIN_CHANGES,
    ChangeRecord,
    by_outlet,
    changes_in,
    for_outlet,
    for_story,
)
from truthnews.models import Article, ArticleRevision, Outlet, Story, utcnow

BBC_BEFORE = (
    '"No hay lugar para la violencia": vehículos quemados, edificios dañados y 1.800 detenidos tras las '
    "multitudinarias protestas en Francia"
)


def test_changes_in_real_cases():
    # Caso real (BBC Mundo, 19/10): el titular pasa de 1.800 a 2.400 detenidos sin avisarlo.
    after = BBC_BEFORE.replace("1.800", "2.400")
    assert changes_in(BBC_BEFORE, after) == [("detenidos", 1800.0, 2400.0, False)]
    # Caso real (France 24): "Otras 39 personas resultaron heridas" no cambia los 4 muertos.
    assert (
        changes_in(
            "Carney confirmó cuatro muertos, pero aún no hay balance de heridos.",
            "Carney confirmó cuatro muertos. Otras 39 personas resultaron heridas.",
        )
        == []
    )


def test_announced_live_and_unchanged():
    assert changes_in("Dos muertos en el incendio", "Actualiza: tres muertos en el incendio") == [
        ("muertos", 2.0, 3.0, True)
    ]
    assert (
        changes_in("El Gobierno eleva a 30 los muertos", "El Gobierno eleva a 40 los muertos")[0][3] is False
    )
    assert changes_in("Directo: 10 detenidos", "Directo: 12 detenidos") == []
    assert changes_in("500 migrantes desalojados", "500 migrantes desalojados en Ceuta") == []
    assert changes_in("Sin cifras", "Tampoco") == []


def test_change_record_needs_a_sample():
    assert ChangeRecord(4, 4).silent_share is None and not ChangeRecord(4, 4).enough
    assert ChangeRecord(MIN_CHANGES, 2).silent_share == 40


def _revision(session, article, before, after, field="title", minutes=0):
    r = ArticleRevision(
        article_id=article.id,
        outlet_id=article.outlet_id,
        field=field,
        before=before,
        after=after,
        before_hash=hashlib.sha256(before.encode()).hexdigest(),
        after_hash=hashlib.sha256(after.encode()).hexdigest(),
        detected_at=utcnow() - timedelta(minutes=minutes),
    )
    session.add(r)
    session.flush()
    return r


def _setup(session):
    now = utcnow()
    o = Outlet(
        slug="bbc",
        name="BBC Mundo",
        homepage="https://bbc",
        country="XX",
        language="es",
        scope="international",
    )
    p = Outlet(
        slug="otro", name="Otro", homepage="https://o", country="XX", language="es", scope="international"
    )
    session.add_all([o, p])
    session.flush()
    st = Story(
        title="Protestas en Francia",
        category="internacional",
        country="XX",
        first_seen=now,
        last_seen=now,
        n_articles=2,
        n_outlets=2,
    )
    session.add(st)
    session.flush()
    arts = []
    for i, (outlet, title) in enumerate(
        [(o, BBC_BEFORE.replace("1.800", "2.400")), (p, "Directo: protestas")]
    ):
        a = Article(
            outlet_id=outlet.id,
            url=f"https://x/{i}",
            url_hash=f"h{i}".ljust(64, "_"),
            title=title,
            published_at=now,
            language="es",
            country="XX",
            category="internacional",
            topics=[],
            story_id=st.id,
        )
        session.add(a)
        session.flush()
        arts.append(a)
    _revision(session, arts[0], BBC_BEFORE, arts[0].title)
    _revision(session, arts[0], "Resumen sin cifras", "Resumen con 3 muertos", field="summary", minutes=5)
    _revision(session, arts[1], "Directo: 10 detenidos", "Directo: 12 detenidos")  # rotacion de directo
    session.commit()
    return o, p, st


def test_queries(session):
    o, p, st = _setup(session)
    changes = for_story(session, st.id)
    assert [(c.outlet, c.noun, c.before, c.after, c.silent, c.field) for c in changes] == [
        ("BBC Mundo", "detenidos", 1800.0, 2400.0, True, "title")
    ]
    assert changes[0].quote_before == BBC_BEFORE and "2.400" in changes[0].quote_after
    assert changes[0].before_at is not None and changes[0].before_at <= changes[0].detected_at
    assert len(for_outlet(session, o.id)) == 1 and for_outlet(session, p.id) == []
    rec = by_outlet(session)
    assert rec[o.id].changes == 1 and rec[o.id].silent == 1 and p.id not in rec


def test_pages(engine, session):
    from fastapi.testclient import TestClient

    from truthnews.config import Settings
    from truthnews.web.app import create_app

    o, p, st = _setup(session)
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    page = client.get(f"/historia/{st.id}").text
    assert "Quién cambió su cifra" in page and "<del>1.800</del> → <ins>2.400</ins>" in page
    assert "en silencio" in page and "#cambios" in page and "Antes · " in page and "Después · " in page
    assert "1.800 detenidos tras" in page and "2.400 detenidos tras" in page
    ficha = client.get("/medio/bbc").text
    assert "Quién cambió su cifra" in ficha and "detenidos" in ficha
    assert "Quién cambió su cifra" not in client.get("/medio/otro").text


def test_ranking_shows_silent_changes_next_to_accuracy(engine, session):
    from fastapi.testclient import TestClient
    from test_reliability import checked

    from truthnews.config import Settings
    from truthnews.web.app import create_app

    o, _, _ = _setup(session)
    checked(session, o, ["verdadero"] * 5)
    session.commit()
    medios = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine)).get("/medios").text
    assert "cifras cambiadas en silencio: 1 de 1" in medios
