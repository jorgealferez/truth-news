"""Autopublicacion en redes (ADR 0018, criterio C9): seleccion, piezas, adaptadores y cola."""

import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from truthnews.models import (
    Article,
    Claim,
    Evidence,
    Outlet,
    SocialPost,
    Story,
    Thread,
    Verification,
)
from truthnews.social import adapters
from truthnews.social.compose import LIMITS, Draft, clip, fit, fmt, length
from truthnews.social.config import SocialSettings
from truthnews.social.queue import run
from truthnews.social.select import candidates

SITE = "https://nosmienten.com"
NOW = datetime.now(UTC)
ALL_CREDS = {
    "BLUESKY_HANDLE": "nosmienten.com",
    "BLUESKY_APP_PASSWORD": "app-pass",
    "MASTODON_URL": "https://mastodon.social",
    "MASTODON_TOKEN": "tok",
    "TELEGRAM_BOT_TOKEN": "123:abc",
    "TELEGRAM_CHAT_ID": "@nosmienten",
    "X_API_KEY": "k",
    "X_API_SECRET": "ks",
    "X_ACCESS_TOKEN": "t",
    "X_ACCESS_SECRET": "ts",
}


def settings(env=None, **kw):
    return SocialSettings(env=env or {}, **kw)


def _outlet(session, slug):
    o = Outlet(
        slug=slug,
        name=slug.upper(),
        homepage=f"https://{slug}.es",
        country="ES",
        language="es",
        scope="national",
    )
    session.add(o)
    session.flush()
    return o


def _story(session, title, figures, n=2, score=4.0):
    st = Story(
        title=title,
        category="politica",
        country="ES",
        first_seen=NOW - timedelta(hours=3),
        last_seen=NOW - timedelta(hours=1),
        n_articles=n,
        n_outlets=n,
        contrast_score=score,
        priority=score,
    )
    session.add(st)
    session.flush()
    for i, fig in enumerate(figures[:n]):
        o = _outlet(session, f"m{st.id}x{i}")
        session.add(
            Article(
                outlet_id=o.id,
                url=f"https://{o.slug}.es/n",
                url_hash=f"{st.id:032d}{i:032d}",
                title=f"{fig} detenidos tras el desalojo del edificio",
                summary=f"La policia practico {fig} detenciones; hubo {fig} detenidos.",
                published_at=NOW - timedelta(hours=2),
                language="es",
                country="ES",
                category="politica",
                story_id=st.id,
            )
        )
    session.flush()
    return st


def _verification(session, story, verdict="falso", with_url=True):
    art = session.query(Article).filter_by(story_id=story.id).first()
    c = Claim(
        article_id=art.id,
        story_id=story.id,
        outlet_id=art.outlet_id,
        text="El paro ha bajado al 5 % este trimestre según el ministerio",
        indicator="paro",
        geo="ES",
        value={"falso": 5.0, "verdadero": 6.0}.get(verdict, 7.0),
        unit="%",
    )
    session.add(c)
    session.flush()
    v = Verification(
        claim_id=c.id,
        verdict=verdict,
        confidence=0.9,
        explanation="La EPA del periodo citado da un 11,2 %, no un 5 %.",
        method="ine",
        checked_at=NOW - timedelta(hours=1),
    )
    session.add(v)
    session.flush()
    session.add(
        Evidence(
            verification_id=v.id,
            source="ine",
            label="INE, Encuesta de Poblacion Activa",
            url="https://www.ine.es/epa" if with_url else "",
            period="2026T2",
            value=11.2,
        )
    )
    session.flush()
    return v


@pytest.fixture()
def content(session):
    good = _story(session, "Desalojo en el edificio de la calle Mayor", [400, 1000])
    _story(session, "Caos en el desalojo de la calle Mayor", [400, 1000])  # lenguaje cargado
    _story(session, "Solo un medio", [3], n=1)
    _story(session, "Sin contraste", [5, 5], score=0.5)
    v = _verification(session, good)
    _verification(session, good, verdict="verdadero")
    _verification(session, good, verdict="enganoso", with_url=False)
    session.add_all(
        [
            Thread(
                title="El edificio de la calle Mayor, de 2019 a hoy",
                status="publicado",
                content={"resumen": "Que paso antes del desalojo.", "por_que_ahora": "Vuelve a la portada."},
                sources=[{"id": "S1", "url": "https://m.es/1"}],
                anchor_story_id=good.id,
                updated_at=NOW,
            ),
            Thread(title="Hilo en revision", status="revision", sources=[{"id": "S1"}], updated_at=NOW),
            Thread(title="Hilo sin fuentes", status="publicado", sources=[], updated_at=NOW),
        ]
    )
    session.commit()
    return good, v


def test_selection_never_review_unsourced_loaded_or_single_outlet(session, content):
    good, v = content
    found = candidates(session, SITE, now=NOW)
    keys = {(c.kind, c.ref_id) for c in found}
    titles = [c.draft.headline for c in found]
    assert ("historia", good.id) in keys and ("verificacion", v.id) in keys
    assert sum(c.kind == "historia" for c in found) == 1  # ni cargada, ni un medio, ni sin contraste
    assert [c.kind for c in found].count("verificacion") == 1  # ni verdadero ni sin enlace a la fuente
    assert [t for t in titles if t.startswith("Hilo:")] == [
        "Hilo: El edificio de la calle Mayor, de 2019 a hoy"
    ]
    assert found == sorted(found, key=lambda c: -c.score)
    story = next(c for c in found if c.kind == "historia")
    assert any("Detenidos: de 400 a 1.000 según el medio." in ln for ln in story.draft.lines)
    assert story.draft.url == f"{SITE}/historia/{good.id}-desalojo-en-el-edificio-de-la-calle-mayor"


def test_every_verification_fits_four_networks(session, content):
    """C9: cada verificacion publicada genera piezas para X, Bluesky, Mastodon y Telegram."""
    for c in candidates(session, SITE, now=NOW):
        for network, (limit, _) in LIMITS.items():
            text = fit(network, c.draft)
            assert length(network, text) <= limit
            assert text.endswith(c.draft.url)


def test_fit_drops_detail_then_clips_headline_never_the_link():
    url = f"{SITE}/historia/1"
    d = Draft("Titular " * 60, ["Detalle " * 30, "Mas detalle " * 30], "Datos:", url)
    for network, (limit, _) in LIMITS.items():
        text = fit(network, d)
        assert length(network, text) <= limit and text.endswith(url)
    assert "…" in fit("x", d)
    short = Draft("Titular", ["Linea 1", "Linea 2"], "Datos:", url)
    assert fit("x", short) == f"Titular\n\nLinea 1\nLinea 2\n\nDatos: {url}"
    assert length("x", f"a {url}") == 2 + 23 and length("bluesky", f"a {url}") == 2 + len(url)
    assert fmt(12500) == "12.500" and fmt(3.4) == "3,4"
    assert clip("uno dos tres cuatro", 10) == "uno dos…"


def test_dry_run_registers_without_sending_no_duplicates_and_quota(session, content):
    calls = []
    client = httpx.Client(transport=httpx.MockTransport(lambda r: calls.append(r) or httpx.Response(500)))
    cfg = settings(quota={"x": 1, "bluesky": 6, "mastodon": 6, "telegram": 8}, per_cycle=2)
    first = run(session, SITE, cfg, client=client, now=NOW)
    assert first["x"] == {"modo": "prueba", "nuevas": 1, "enviadas": 0, "errores": 0}
    assert first["telegram"]["nuevas"] == 2 and not calls
    posts = session.query(SocialPost).all()
    assert {p.status for p in posts} == {"prueba"} and all(p.link.startswith(SITE) for p in posts)
    second = run(session, SITE, cfg, client=client, now=NOW + timedelta(minutes=60))
    assert second["x"]["nuevas"] == 0  # cupo diario agotado
    assert second["telegram"]["nuevas"] == 1  # el tercer candidato, nunca un repetido
    keys = [(p.network, p.kind, p.ref_id) for p in session.query(SocialPost)]
    assert len(keys) == len(set(keys))
    tomorrow = run(session, SITE, cfg, client=client, now=NOW + timedelta(days=1))
    assert tomorrow["x"]["nuevas"] == 1
    assert run(session, SITE, settings(enabled=False)) == {"activo": False}


def _fake_networks(fail=()):
    seen = []

    def handler(req: httpx.Request) -> httpx.Response:
        seen.append(req)
        host, path = req.url.host, req.url.path
        if any(f in host for f in fail):
            return httpx.Response(503, text="caido")
        if path.endswith("createSession"):
            return httpx.Response(200, json={"accessJwt": "jwt", "did": "did:plc:abc"})
        if path.endswith("uploadBlob"):
            return httpx.Response(200, json={"blob": {"$type": "blob", "ref": {"$link": "x"}}})
        if path.endswith("createRecord"):
            return httpx.Response(200, json={"uri": "at://did:plc:abc/app.bsky.feed.post/3k", "cid": "c"})
        if path == "/api/v2/media":
            return httpx.Response(200, json={"id": "77"})
        if path == "/api/v1/statuses":
            return httpx.Response(200, json={"id": "88", "url": "https://mastodon.social/@n/88"})
        if path.endswith("/sendPhoto"):
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})
        if path == "/2/tweets":
            return httpx.Response(201, json={"data": {"id": "1001", "text": "t"}})
        return httpx.Response(404)

    return seen, httpx.Client(transport=httpx.MockTransport(handler))


def test_sends_with_credentials_and_records_each_post(session, content):
    seen, client = _fake_networks()
    out = run(session, SITE, settings(env=ALL_CREDS, per_cycle=1), client=client, now=NOW)
    for network in ("x", "bluesky", "mastodon", "telegram"):
        assert out[network] == {"modo": "envio", "nuevas": 1, "enviadas": 1, "errores": 0}
    posts = {p.network: p for p in session.query(SocialPost)}
    assert posts["bluesky"].external_url == "https://bsky.app/profile/nosmienten.com/post/3k"
    assert posts["mastodon"].external_url.endswith("/88")
    assert posts["telegram"].external_url == "https://t.me/nosmienten/9"
    assert posts["x"].external_url == "https://x.com/i/web/status/1001"
    assert all(p.status == "enviado" and p.sent_at and p.attempts == 1 for p in posts.values())
    record = json.loads(next(r for r in seen if r.url.path.endswith("createRecord")).content)["record"]
    assert record["embed"]["external"]["thumb"] and record["facets"][0]["features"][0]["uri"].startswith(SITE)
    tweet = next(r for r in seen if r.url.path == "/2/tweets")
    assert (
        tweet.headers["Authorization"].startswith("OAuth ")
        and "oauth_signature=" in tweet.headers["Authorization"]
    )
    assert "Idempotency-Key" in next(r for r in seen if r.url.path == "/api/v1/statuses").headers


def test_failure_is_recorded_stops_the_network_and_retries_next_cycle(session, content):
    _, broken = _fake_networks(fail=("api.telegram.org",))
    out = run(session, SITE, settings(env=ALL_CREDS, per_cycle=2), client=broken, now=NOW)
    assert out["telegram"] == {"modo": "envio", "nuevas": 1, "enviadas": 0, "errores": 1}
    assert out["mastodon"]["enviadas"] == 2
    failed = session.query(SocialPost).filter_by(network="telegram").one()
    assert failed.status == "error" and "503" in failed.error and failed.attempts == 1
    _, fixed = _fake_networks()
    again = run(session, SITE, settings(env=ALL_CREDS, per_cycle=2), client=fixed, now=NOW)
    assert again["telegram"]["enviadas"] == 3  # el reintento y dos nuevas (el reintento no gasta el tope)
    session.refresh(failed)
    assert failed.status == "enviado" and failed.attempts == 2 and failed.error is None


def test_settings_quota_and_credentials(monkeypatch):
    monkeypatch.setenv("SOCIAL_DAILY_QUOTA", "x:2, telegram:10, nada:3, bluesky:abc")
    s = SocialSettings()
    assert s.quota == {"x": 2, "bluesky": 6, "mastodon": 6, "telegram": 10}
    assert settings(env=ALL_CREDS).credentials("x")["X_API_KEY"] == "k"
    assert settings(env={"X_API_KEY": "k"}).credentials("x") is None
    assert settings(env=ALL_CREDS, dry_run=True).credentials("telegram") is None


def test_link_facets_use_utf8_byte_offsets():
    text = f"Desalojo en Logroño\n\nDatos: {SITE}/historia/1"
    (facet,) = adapters.link_facets(text)
    start, end = facet["index"]["byteStart"], facet["index"]["byteEnd"]
    assert text.encode()[start:end].decode() == f"{SITE}/historia/1"


def test_oauth1_header_is_deterministic_and_signed():
    creds = {k: ALL_CREDS[k] for k in ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET")}
    a = adapters.oauth1_header("POST", adapters.X.URL, creds, nonce="n", ts="1")
    assert a == adapters.oauth1_header("post", adapters.X.URL, creds, nonce="n", ts="1")
    assert a != adapters.oauth1_header(
        "POST", adapters.X.URL, {**creds, "X_API_SECRET": "otro"}, nonce="n", ts="1"
    )
    assert 'oauth_consumer_key="k"' in a and 'oauth_signature_method="HMAC-SHA1"' in a


def test_adapter_errors_and_telegram_text_only():
    client = httpx.Client(
        transport=httpx.MockTransport(
            lambda r: (
                httpx.Response(200, json={"ok": False, "description": "chat not found"})
                if "sendMessage" in r.url.path
                else httpx.Response(200, text="no json")
            )
        )
    )
    tg = adapters.Telegram(ALL_CREDS, client)
    with pytest.raises(adapters.SendError, match="chat not found"):
        tg.send("hola", SITE, None, "t")
    with pytest.raises(adapters.SendError, match="no JSON"):
        adapters.Mastodon(ALL_CREDS, client).send("hola", SITE, None, "t")


def test_admin_shows_social_queue_without_secrets(engine, session, content, monkeypatch):
    from fastapi.testclient import TestClient

    from truthnews.config import Settings
    from truthnews.social.queue import status
    from truthnews.web.app import create_app

    run(session, SITE, settings(), now=NOW)
    session.commit()
    info = status(session, settings(env={"TELEGRAM_BOT_TOKEN": "x", "TELEGRAM_CHAT_ID": "@c"}), now=NOW)
    modes = {n["network"]: (n["mode"], n["today"]) for n in info["networks"]}
    assert modes["telegram"] == ("envio", 2) and modes["x"] == ("prueba", 2)
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "secreto-del-bot")
    client = TestClient(create_app(Settings(database_url="sqlite://", admin_password="clave"), engine=engine))
    page = client.get("/admin", auth=("admin", "clave")).text
    assert "<h2>Redes</h2>" in page and "modo prueba (sin credenciales)" in page
    assert "Verificación: Falso" in page and "secreto-del-bot" not in page
