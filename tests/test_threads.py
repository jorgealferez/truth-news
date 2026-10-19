from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient

from truthnews.ai import threads
from truthnews.ai.client import AIError, AIResult
from truthnews.config import Settings
from truthnews.models import Article, Outlet, Story, Thread
from truthnews.web.app import create_app

NOW = datetime.now(UTC)


def _story(session, title="Llegada masiva de migrantes a Ceuta tras la crisis con Marruecos", n=3, days=0):
    when = NOW - timedelta(days=days)
    st = Story(
        title=title,
        category="sucesos",
        country="ES",
        first_seen=when,
        last_seen=when,
        n_articles=n,
        n_outlets=n,
        priority=5,
    )
    session.add(st)
    session.flush()
    for i in range(n):
        o = session.query(Outlet).filter_by(slug=f"m{i}").one_or_none()
        if o is None:
            o = Outlet(
                slug=f"m{i}",
                name=f"Medio {i}",
                homepage="https://m",
                country="ES",
                language="es",
                scope="national",
            )
            session.add(o)
            session.flush()
        session.add(
            Article(
                outlet_id=o.id,
                story_id=st.id,
                url=f"https://m/{st.id}/{i}",
                url_hash=f"{st.id:032d}{i:032d}",
                title=title,
                summary="Ceuta Marruecos migrantes frontera",
                published_at=when,
                language="es",
                country="ES",
                category="sucesos",
                topics=[],
            )
        )
    session.flush()
    return st


def fake_articles(query, start, end, max_records=15):
    assert start < end
    return [
        {
            "date": datetime(2021, 5, 18, tzinfo=UTC),
            "title": "Thousands of migrants enter Ceuta",
            "domain": "reuters.com",
            "language": "English",
            "url": "https://reuters.com/ceuta",
        },
        {
            "date": datetime(2021, 4, 23, tzinfo=UTC),
            "title": "Polisario leader treated in Spanish hospital",
            "domain": "bbc.com",
            "language": "English",
            "url": "https://bbc.com/ghali",
        },
    ]


def fake_encyclopedia(query, limit=2):
    return [
        {
            "title": "Crisis de Ceuta de 2021",
            "extract": "En mayo de 2021 unas 10.000 personas entraron.",
            "url": "https://es.wikipedia.org/wiki/Crisis",
        }
    ]


class FakeAI:
    def __init__(self, thread_data=None, fail=False):
        self.thread_data, self.fail, self.calls = thread_data, fail, []

    def structured(self, system, user, schema):
        self.calls.append(system)
        if self.fail:
            raise AIError("rechazo")
        if system == threads.PLAN_SYSTEM:
            assert "HISTORIA" in user and "Medio 0" in user
            return AIResult(
                data={
                    "tema": "Ceuta Marruecos",
                    "pregunta_central": "Por que",
                    "actores": ["Marruecos", "Ceuta"],
                    "consultas_hemeroteca": [
                        {
                            "consulta": "ceuta morocco",
                            "desde": "2021-04-01",
                            "hasta": "2021-06-30",
                            "motivo": "crisis",
                        },
                        {
                            "consulta": "x",
                            "desde": "2030-01-01",
                            "hasta": "2021-01-01",
                            "motivo": "periodo invalido",
                        },
                    ],
                    "consultas_enciclopedia": ["Crisis de Ceuta 2021"],
                    "hipotesis": [{"hecho": "Ghali", "por_que_comprobarlo": "fechas"}],
                },
                model="m",
                usage={"output_tokens": 10},
            )
        assert "CORPUS" in user and '"G1"' in user and '"W1"' in user
        return AIResult(data=self.thread_data, model="modelo-hilo", usage={"output_tokens": 99})


def content(extra_number="10.000"):
    return {
        "titular": "De Ghali a Ceuta",
        "resumen": "Resumen.",
        "por_que_ahora": "Porque vuelve la presion migratoria.",
        "cronologia": [
            {
                "fecha": "2021-05-18",
                "hecho": f"Entran {extra_number} personas",
                "quien": "",
                "tipo": "hizo",
                "fuentes": ["G1", "W1"],
            },
            {
                "fecha": "2021-04-23",
                "hecho": "Ghali ingresa en un hospital",
                "quien": "",
                "tipo": "hizo",
                "fuentes": ["G2"],
            },
            {"fecha": "2021-05-20", "hecho": "Sin fuente", "quien": "", "tipo": "dijo", "fuentes": ["G99"]},
        ],
        "que_dijo_quien": [],
        "conexiones": [
            {
                "de": "Ghali en Espana",
                "a": "Entrada en Ceuta",
                "explicacion": "Fechas",
                "solidez": "probable",
                "fuentes": ["G1", "G2"],
            }
        ],
        "lo_que_no_sabemos": ["Si hubo orden expresa"],
    }


def test_build_thread_grounds_sources_and_sorts(session):
    st = _story(session)
    _story(session, title="Marruecos y Ceuta: nueva crisis en la frontera de Ceuta", days=40)
    ai = FakeAI(content())
    th = threads.build_thread(session, st, ai, articles=fake_articles, encyclopedia=fake_encyclopedia)
    assert ai.calls == [threads.PLAN_SYSTEM, threads.THREAD_SYSTEM]
    assert th.status == "publicado" and th.model == "modelo-hilo"
    assert th.grounding == {"sin_fuente_descartados": 1, "cifras_sin_fuente": [], "ok": True}
    assert [e["fecha"] for e in th.content["cronologia"]] == ["2021-04-23", "2021-05-18"]
    ids = {s["id"] for s in th.sources}
    assert {"G1", "G2", "W1"} <= ids and any(i.startswith("S") for i in ids)
    # Un refresco reutiliza el mismo hilo de la historia.
    again = threads.build_thread(
        session, st, FakeAI(content()), articles=fake_articles, encyclopedia=fake_encyclopedia
    )
    assert again.id == th.id


def test_unsupported_figure_sends_thread_to_review(session):
    st = _story(session)
    th = threads.build_thread(
        session, st, FakeAI(content("12.345")), articles=fake_articles, encyclopedia=fake_encyclopedia
    )
    assert th.status == "revision" and th.grounding["cifras_sin_fuente"] == ["12345"]


def test_failing_sources_do_not_break_the_corpus(session):
    st = _story(session)

    def boom(*a, **k):
        raise RuntimeError("caido")

    plan = {
        "tema": "x",
        "actores": [],
        "consultas_hemeroteca": [{"consulta": "q", "desde": "2021-01-01", "hasta": "2021-02-01"}],
        "consultas_enciclopedia": ["q"],
    }
    assert threads.build_corpus(session, st, plan, articles=boom, encyclopedia=boom) == []


def test_run_picks_front_stories_and_respects_refresh(session):
    st = _story(session)
    out = threads.run(
        session, FakeAI(content()), limit=2, articles=fake_articles, encyclopedia=fake_encyclopedia
    )
    assert out == {"threads": 1, "threads_in_revision": 0, "threads_failed": 0}
    assert (
        threads.run(
            session, FakeAI(content()), limit=2, articles=fake_articles, encyclopedia=fake_encyclopedia
        )["threads"]
        == 0
    )
    session.query(Thread).update({Thread.updated_at: NOW - timedelta(hours=13)})
    assert threads.run(session, FakeAI(fail=True), limit=2)["threads_failed"] == 1
    assert st.id


def test_thread_pages(engine, session):
    st = _story(session)
    th = threads.build_thread(
        session, st, FakeAI(content()), articles=fake_articles, encyclopedia=fake_encyclopedia
    )
    hidden = Thread(title="En revision", status="revision")
    session.add(hidden)
    session.commit()
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))
    page = client.get(f"/hilo/{th.id}").text
    for needle in (
        "De Ghali a Ceuta",
        "Por qué ahora",
        "Lo que conecta los hechos",
        "Probable",
        "https://reuters.com/ceuta",
        "Lo que no sabemos",
        'class="timeline"',
    ):
        assert needle in page, needle
    assert client.get(f"/hilo/{hidden.id}").status_code == 404
    assert client.get("/hilo/9999").status_code == 404
    assert f'href="/hilo/{th.id}"' in client.get(f"/historia/{st.id}").text
    home = client.get("/").text
    assert "Por qué está pasando" in home and "De Ghali a Ceuta" in home
    assert f"/hilo/{th.id}</loc>" in client.get("/sitemap.xml").text
