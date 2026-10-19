import json
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace as NS

import pytest
from sqlalchemy import select

from truthnews.ai import pipeline as ai_pipeline
from truthnews.ai.client import FALLBACK_BETA, AIClient, AIError, AIResult
from truthnews.ai.topics import build_topics, topics_schema
from truthnews.ai.writer import build_dossier, check_grounding, piece_schema, write_pieces
from truthnews.analysis.verify import Verifier
from truthnews.config import Settings
from truthnews.data import Observation
from truthnews.models import Article, Outlet, Piece, Story, Topic

NOW = datetime.now(UTC)


# --- Cliente: parametros enviados y manejo de respuestas --------------------------------------------
class FakeStream:
    def __init__(self, msg, calls, kwargs):
        self.msg, self.calls, self.kwargs = msg, calls, kwargs

    def __enter__(self):
        self.calls.append(self.kwargs)
        return self

    def __exit__(self, *exc):
        return False

    def get_final_message(self):
        return self.msg


def fake_sdk(msg, calls):
    return NS(beta=NS(messages=NS(stream=lambda **kw: FakeStream(msg, calls, kw))))


def message(text='{"ok": 1}', stop="end_turn"):
    content = [NS(type="thinking", thinking=""), NS(type="text", text=text)] if text is not None else []
    return NS(
        content=content,
        stop_reason=stop,
        stop_details=NS(category="cyber"),
        model="claude-opus-5-5",
        usage=NS(input_tokens=10, output_tokens=5, cache_read_input_tokens=0, cache_creation_input_tokens=8),
    )


def test_client_sends_structured_cached_request_with_fallbacks():
    calls = []
    res = AIClient(client=fake_sdk(message(), calls), effort="high").structured(
        "SYS", "USER", {"type": "object"}
    )
    assert res.data == {"ok": 1} and res.usage["cache_creation_input_tokens"] == 8
    kw = calls[0]
    assert kw["model"] == "claude-opus-5-5" and kw["thinking"] == {"type": "adaptive"}
    assert kw["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert kw["output_config"]["format"]["type"] == "json_schema" and kw["output_config"]["effort"] == "high"
    assert kw["fallbacks"] == "default" and kw["betas"] == [FALLBACK_BETA]


@pytest.mark.parametrize(
    "msg,err",
    [
        (message(stop="refusal"), "rechazo"),
        (message(stop="max_tokens"), "truncada"),
        (message(text=None), "sin texto"),
        (message(text="{no"), "JSON invalido"),
    ],
)
def test_client_errors(msg, err):
    with pytest.raises(AIError, match=err):
        AIClient(client=fake_sdk(msg, [])).structured("s", "u", {})


def test_real_sdk_serializes_request(monkeypatch):
    """Pasa por el SDK oficial con un transporte simulado: la peticion se construye y la respuesta se lee."""
    import anthropic
    import httpx2

    seen = {}

    def handler(request):
        seen["body"] = json.loads(request.content)
        seen["beta"] = request.headers.get("anthropic-beta")
        events = [
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "id": "msg_1",
                        "type": "message",
                        "role": "assistant",
                        "model": "claude-opus-5-5",
                        "content": [],
                        "stop_reason": None,
                        "stop_sequence": None,
                        "usage": {"input_tokens": 5, "output_tokens": 0},
                    },
                },
            ),
            (
                "content_block_start",
                {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": '{"temas": []}'},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn", "stop_sequence": None},
                    "usage": {"output_tokens": 7},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        ]
        body = "".join(f"event: {e}\ndata: {json.dumps(d)}\n\n" for e, d in events)
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body.encode())

    sdk = anthropic.Anthropic(
        api_key="test", http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler))
    )
    res = AIClient(client=sdk).structured("SYS", "USER", topics_schema())
    assert res.data == {"temas": []}
    body = seen["body"]
    assert body["fallbacks"] == "default" and FALLBACK_BETA in seen["beta"]
    assert body["output_config"]["format"]["schema"]["required"] == ["temas"] and body["stream"] is True


# --- Datos de prueba ------------------------------------------------------------------------------------
@pytest.fixture()
def topic_world(session):
    outs = [
        Outlet(slug=s, name=s.upper(), homepage="https://x", country="ES", language="es", scope="national")
        for s in ("aa", "bb", "cc")
    ]
    session.add_all(outs)
    session.flush()
    stories = []
    for j, title in enumerate(
        [
            "Protestas en Francia dejan 2.000 detenidos",
            "Macron culpa a la extrema izquierda",
            "Partido de fútbol",
        ]
    ):
        st = Story(
            title=title,
            category="internacional",
            country="ES",
            first_seen=NOW,
            last_seen=NOW,
            n_articles=2,
            n_outlets=2,
        )
        session.add(st)
        session.flush()
        for k, o in enumerate(outs[:2] if j < 2 else outs[1:]):
            session.add(
                Article(
                    outlet_id=o.id,
                    url=f"https://x/{j}/{k}",
                    url_hash=f"{j}{k}".zfill(64),
                    title=f"{title} ({o.slug})",
                    summary="2.000 detenidos y 500 heridos",
                    published_at=NOW - timedelta(minutes=10 * k),
                    language="es",
                    country="ES",
                    category="internacional",
                    topics=[],
                    story_id=st.id,
                )
            )
        stories.append(st)
    session.flush()
    return outs, stories


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
        return AIResult(data=r, model="claude-opus-5-5", usage={"output_tokens": 1})


def topics_reply(ids):
    return {
        "temas": [
            {"titulo": "Protestas en Francia", "categoria": "internacional", "historias": ids},
            {"titulo": "Inventado", "categoria": "internacional", "historias": [999, 998]},
            {"titulo": "Mala categoria", "categoria": "magia", "historias": ids},
        ]
    }


def test_build_topics_validates_and_keeps_identity(session, topic_world):
    _, stories = topic_world
    ids = [stories[0].id, stories[1].id]
    out = build_topics(session, FakeAI([topics_reply(ids)]))
    assert out["topics"] == 1 and out["topics_created"] == 1
    tp = session.scalars(select(Topic)).one()
    assert tp.n_stories == 2 and tp.n_outlets == 2 and stories[2].topic_id is None
    again = build_topics(
        session,
        FakeAI(
            [{"temas": [{"titulo": "Francia, protestas", "categoria": "internacional", "historias": ids}]}]
        ),
    )
    assert again["topics_created"] == 0 and session.scalars(select(Topic)).one().title == "Francia, protestas"
    build_topics(session, FakeAI([{"temas": []}]))
    assert stories[0].topic_id is None


def good_piece(story_ids, slugs):
    return {
        "titular": "Francia: cifras distintas según el medio",
        "entradilla": "Los medios dan 2.000 detenidos.",
        "que_dice_cada_medio": [
            {"medio_slug": s, "sintesis": "Da 2.000 detenidos.", "enfoque": "Balance"} for s in slugs
        ],
        "coincidencias": ["500 heridos"],
        "diferencias": [{"aspecto": "Tono", "detalle": "Uno usa 'caos'"}],
        "datos": [{"dato": "2.000 detenidos", "fuente": "AA"}],
        "valoracion": {
            "conclusion": "Cobertura coherente.",
            "confianza": "media",
            "lo_que_no_sabemos": ["x"],
        },
        "analisis": [{"subtitulo": "Qué pasó", "parrafos": ["Según AA, 2.000 detenidos y 3 medios."]}],
        "opinion": {"titulo": "Contar bien", "parrafos": ["Opinión basada en datos."]},
        "historias_citadas": story_ids,
    }


def test_dossier_grounding_and_pieces(session, topic_world):
    outs, stories = topic_world
    ids = [stories[0].id, stories[1].id]
    build_topics(session, FakeAI([topics_reply(ids)]))
    tp = session.scalars(select(Topic)).one()
    period = f"{NOW.year}-{NOW.month:02d}"
    verifier = Verifier(
        lambda s, g, label: Observation("eurostat", label, "https://ec.europa.eu/x", period, 10.0)
    )
    tp.category = "economia"
    dossier = build_dossier(session, tp, verifier)
    assert {s["id"] for s in dossier["historias"]} == set(ids) and dossier["datos_oficiales_de_contexto"]
    ok = check_grounding(good_piece(ids, ["aa", "bb"]), dossier, set(ids), {"aa", "bb"})
    assert ok["ok"], ok
    bad = good_piece(ids + [999], ["aa", "zz"])
    bad["analisis"][0]["parrafos"].append("Y 7.777 heridos más.")
    g = check_grounding(bad, dossier, set(ids), {"aa", "bb"})
    assert g == {
        "cifras_sin_fuente": ["7777"],
        "medios_desconocidos": ["zz"],
        "historias_desconocidas": [999],
        "ok": False,
    }

    ai = FakeAI([good_piece(ids, ["aa", "bb"])])
    pieces = write_pieces(session, tp, ai, verifier)
    assert [p.kind for p in pieces] == ["analisis", "opinion"] and all(
        p.status == "publicada" for p in pieces
    )
    assert "DOSSIER" in ai.users[0] and "2.000 detenidos" in ai.users[0]
    assert write_pieces(session, tp, FakeAI([]), verifier) == []  # dossier sin cambios: no se regenera
    stories[0].title = "Cambio"
    session.flush()
    revision = write_pieces(session, tp, FakeAI([bad]), verifier)
    assert revision[0].status == "revision"


def test_ai_pipeline(session, topic_world):
    _, stories = topic_world
    ids = [stories[0].id, stories[1].id]
    assert "desactivada" in ai_pipeline.run(session, Settings())["ai"]
    settings = Settings(ai_piece_refresh_minutes=0)  # la cadencia minima se prueba aparte
    out = ai_pipeline.run(
        session,
        settings,
        ai=FakeAI([topics_reply(ids), good_piece(ids, ["aa", "bb"])]),
        verifier=Verifier(lambda s, g, label: None),
    )
    assert out["pieces_written"] == 1 and out["pieces_in_revision"] == 0
    assert session.scalars(select(Piece)).all()
    assert "error" in ai_pipeline.run(session, settings, ai=FakeAI([AIError("rechazo")]))
    stories[1].title = "Otra"
    session.flush()
    failed = ai_pipeline.run(
        session,
        settings,
        ai=FakeAI([topics_reply(ids), AIError("x")]),
        verifier=Verifier(lambda s, g, label: None),
    )
    assert failed["failed"] == 1


def test_schemas_are_strict():
    for schema in (topics_schema(), piece_schema()):
        assert schema["additionalProperties"] is False and schema["required"]


def test_ai_pipeline_writes_pieces_in_parallel(session, monkeypatch):
    """Las llamadas de las piezas se solapan; los dossieres y el guardado van en serie y en orden."""
    import threading
    import time

    topics = [type("T", (), {"id": i})() for i in range(4)]
    monkeypatch.setattr(ai_pipeline, "prepare_piece", lambda s, t, v: ({"t": t.id}, f"h{t.id}"))
    running, peak, lock = [0], [0], threading.Lock()

    def ask(ai, dossier):
        with lock:
            running[0] += 1
            peak[0] = max(peak[0], running[0])
        time.sleep(0.2)
        with lock:
            running[0] -= 1
        if dossier["t"] == 1:
            raise AIError("x")
        return dossier

    stored = []
    monkeypatch.setattr(ai_pipeline, "ask_piece", ask)
    monkeypatch.setattr(
        ai_pipeline, "store_pieces", lambda s, t, d, h, r: stored.append(t.id) or [Piece(status="revision")]
    )
    written, revision, failed = ai_pipeline.write_batch(session, None, topics, None, 3, 3)
    assert peak[0] == 3 and stored == [0, 2]  # el tope de piezas (3) se respeta: el tema 3 no entra
    assert (written, revision, failed) == (2, 2, 1)


# --- Coste (ADR 0054) ---------------------------------------------------------------------------------
def test_call_cost_uses_model_prices_and_charges_unknown_at_the_top():
    from truthnews.ai import cost

    usage = {"input_tokens": 1_000_000, "output_tokens": 100_000, "cache_read_input_tokens": 0}
    assert cost.call_cost("claude-opus-5-5", usage) == pytest.approx(4.0 + 2.0)
    assert cost.call_cost("claude-opus-5", usage) == pytest.approx(5.0 + 2.5)  # no se confunde con 5-5
    assert cost.call_cost("claude-haiku-5-5", usage) == pytest.approx(0.1 + 0.05)
    assert cost.call_cost("modelo-nuevo", usage) == pytest.approx(5.0 + 2.5)


def test_client_charges_every_call_and_stops_at_the_daily_budget(monkeypatch):
    from truthnews.ai import cost

    meter = cost.Meter(spent_before=0.0, daily_budget=0.0001)
    monkeypatch.setattr(cost, "METER", meter)
    with pytest.raises(AIError, match="rechazo"):  # un rechazo tambien se paga
        AIClient(client=fake_sdk(message(stop="refusal"), [])).structured("s", "u", {})
    assert meter.calls == 1 and meter.spent > 0
    calls = []
    meter.spent_before = 1.0
    with pytest.raises(AIError, match="presupuesto diario"):
        AIClient(client=fake_sdk(message(), calls)).structured("s", "u", {})
    assert calls == []  # pasado el tope no se llama
    summary = meter.summary()
    assert summary["llamadas"] == 1 and summary["por_modelo"]["claude-opus-5-5"] > 0


def test_unlimited_budget_never_blocks():
    from truthnews.ai import cost

    meter = cost.Meter(spent_before=1e6, daily_budget=0)
    meter.check()


def test_topic_with_recent_piece_gives_its_slot_to_the_next(session, monkeypatch):
    from datetime import timedelta

    from truthnews.models import utcnow

    old, fresh, empty = (
        Topic(title=t, category="internacional", country="ES", first_seen=NOW, last_seen=NOW)
        for t in ("a", "b", "c")
    )
    session.add_all([old, fresh, empty])
    session.flush()
    for tp, age in ((old, timedelta(hours=5)), (fresh, timedelta(minutes=10))):
        session.add(
            Piece(
                topic_id=tp.id,
                kind="analisis",
                status="publicada",
                title="t",
                dek="d",
                model="m",
                input_hash="x",
                created_at=utcnow() - age,
            )
        )
    session.flush()
    refresh = timedelta(minutes=120)
    assert not ai_pipeline.recent_piece(session, old, refresh)
    assert ai_pipeline.recent_piece(session, fresh, refresh)
    assert not ai_pipeline.recent_piece(session, empty, refresh)
    asked = []
    monkeypatch.setattr(ai_pipeline, "prepare_piece", lambda s, t, v: asked.append(t.id) or None)
    ai_pipeline.write_batch(session, None, [old, fresh, empty], None, 6, 1, refresh)
    assert asked == [old.id, empty.id]


def test_worker_sums_todays_ai_cost(session):
    from truthnews.models import CrawlRun
    from truthnews.worker import spent_today

    session.add_all(
        [
            CrawlRun(started_at=NOW, stats={"ai_cost": {"usd": 1.5}}),
            CrawlRun(started_at=NOW, stats={"seconds": {}}),
            CrawlRun(started_at=NOW - timedelta(days=2), stats={"ai_cost": {"usd": 9}}),
        ]
    )
    session.flush()
    assert spent_today(session, NOW) == pytest.approx(1.5)


def test_ai_step_reports_cost_per_part(session, topic_world, monkeypatch):
    from truthnews.ai import cost

    _, stories = topic_world
    ids = [stories[0].id, stories[1].id]

    class Paying(FakeAI):
        def structured(self, system, user, schema):
            cost.METER.charge("claude-opus-5-5", {"output_tokens": 1_000_000})  # 20 USD por llamada
            return super().structured(system, user, schema)

    out = ai_pipeline.run(
        session,
        Settings(ai_piece_refresh_minutes=0),
        ai=Paying([topics_reply(ids), good_piece(ids, ["aa", "bb"])]),
        verifier=Verifier(lambda s, g, label: None),
    )
    assert out["coste_usd"] == {"traducciones": 0, "declaraciones": 0, "temas": 20.0, "piezas": 20.0}
