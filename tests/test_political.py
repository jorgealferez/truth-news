import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx
from sqlalchemy import select

from truthnews import registry
from truthnews.config import Settings
from truthnews.crawler import political
from truthnews.models import PoliticalStatement
from truthnews.registry import ActorSpec, ChannelSpec, RegistryError

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>P</title>
<item><title>Nota de prensa sobre vivienda</title><link>https://partido.test/nota-1</link>
<description>&lt;p&gt;El partido propone...&lt;/p&gt;</description>
<pubDate>Sun, 18 Oct 2026 10:00:00 +0000</pubDate></item>
<item><title>Sin fecha</title><link>https://partido.test/nota-2</link></item>
</channel></rss>"""
MASTODON = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>@p</title>
<item><link>https://mastodon.test/@p/1</link>
<description>&lt;p&gt;Post sin titulo con un texto largo&lt;/p&gt;</description>
<pubDate>Sun, 18 Oct 2026 11:00:00 +0000</pubDate></item></channel></rss>"""
BSKY = {
    "feed": [
        {
            "post": {
                "uri": "at://did:plc:x/app.bsky.feed.post/3abc",
                "record": {"text": "Hoy en el Congreso", "createdAt": "2026-10-18T12:00:00.000Z"},
            }
        },
        {
            "post": {
                "uri": "at://did:plc:y/app.bsky.feed.post/3zzz",
                "record": {"text": "ajeno", "createdAt": "2026-10-18T12:00:00Z"},
            },
            "reason": {"$type": "repost"},
        },
        {
            "post": {
                "uri": "at://did:plc:x/app.bsky.feed.post/3def",
                "record": {"text": "  ", "createdAt": "2026-10-18T12:00:00Z"},
            }
        },
    ]
}
TG = (
    '<div class="tgme_widget_message" data-post="canal/10">'
    '<div class="tgme_widget_message_text js-message_text">'
    "Mensaje <b>del</b> partido<br/>segunda linea</div>"
    '<time datetime="2026-10-18T13:00:00+00:00"></time></div>'
    '<div class="tgme_widget_message" data-post="otro/5">'
    '<div class="tgme_widget_message_text">reenviado</div>'
    '<time datetime="2026-10-18T13:00:00+00:00"></time></div>'
)

ACTORS = [
    ActorSpec(
        "a",
        "A",
        "Partido A",
        "https://partido.test",
        "ES",
        None,
        (
            ChannelSpec("web", url="https://partido.test/feed"),
            ChannelSpec("mastodon", url="https://mastodon.test/@p.rss", verified="web"),
            ChannelSpec("bluesky", handle="partido.test", verified="dominio"),
            ChannelSpec("telegram", handle="canal", verified="web"),
        ),
    ),
    ActorSpec(
        "b",
        "B",
        "Partido B",
        "https://bloqueado.test",
        "ES",
        None,
        (
            ChannelSpec("web", url="https://bloqueado.test/feed"),
            ChannelSpec("web", url="https://prohibido.test/feed"),
        ),
    ),
]


@respx.mock
def test_run_reads_four_channels_respects_blocks_and_dedupes(session):
    respx.get(
        url__regex=r"https://(partido|mastodon|public\.api\.bsky|t|bloqueado)\.(test|app|me)/robots.txt"
    ).mock(return_value=httpx.Response(404))
    respx.get("https://prohibido.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /")
    )
    respx.get("https://public.api.bsky.app/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://t.me/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://partido.test/feed").mock(return_value=httpx.Response(200, content=RSS))
    respx.get("https://mastodon.test/@p.rss").mock(return_value=httpx.Response(200, content=MASTODON))
    respx.get(url__startswith="https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed").mock(
        return_value=httpx.Response(200, json=BSKY)
    )
    respx.get("https://t.me/s/canal").mock(return_value=httpx.Response(200, text=TG))
    respx.get("https://bloqueado.test/feed").mock(return_value=httpx.Response(403))
    settings = Settings(database_url="sqlite://", per_domain_delay_seconds=0)

    out = political.run(session, settings, ACTORS)
    assert out["channels"] == 6 and out["channels_ok"] == 4 and out["new"] == 4
    assert out["failed"] == {
        "b:web:https://bloqueado.test/feed": "http 403",
        "b:web:https://prohibido.test/feed": "robots",
    }
    rows = {r.channel: r for r in session.scalars(select(PoliticalStatement))}
    assert (
        rows["web"].text == "Nota de prensa sobre vivienda" and rows["web"].summary == "El partido propone..."
    )
    assert rows["mastodon"].text == "Post sin titulo con un texto largo"
    assert rows["bluesky"].url == "https://bsky.app/profile/partido.test/post/3abc"
    assert (
        rows["telegram"].url == "https://t.me/canal/10"
        and rows["telegram"].text == "Mensaje del partido segunda linea"
    )
    assert all(r.actor == "a" and r.country == "ES" and r.story_id is None for r in rows.values())
    assert political.run(session, settings, ACTORS)["new"] == 0  # sin duplicados


@respx.mock
def test_channel_errors_are_reported_not_raised(session):
    respx.get("https://caido.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://caido.test/feed").mock(side_effect=httpx.ConnectError("x"))
    actor = ActorSpec(
        "c", "C", "C", "https://caido.test", "ES", None, (ChannelSpec("web", url="https://caido.test/feed"),)
    )
    out = political.run(session, Settings(database_url="sqlite://", per_domain_delay_seconds=0), [actor])
    assert out["failed"] == {"c:web:https://caido.test/feed": "error ConnectError"}


def test_parsers_edge_cases():
    long = "palabra " * 80
    assert political._short(long).endswith("…") and len(political._short(long)) <= 280
    assert political._date(None) is None and political._date("no es fecha") is None
    assert political._date("2026-10-18T12:00:00").tzinfo is not None
    assert political.parse_telegram("<div>nada</div>", "canal") == []


def test_registry_parties_symmetric_and_documented():
    actors = registry.load_political()
    assert [a.slug for a in actors] == sorted(a.slug for a in actors)
    assert {
        "pp",
        "psoe",
        "vox",
        "sumar",
        "erc",
        "junts",
        "ehbildu",
        "pnv",
        "podemos",
        "bng",
        "cc",
        "upn",
    } == {a.slug for a in actors}
    for a in actors:
        assert a.channels or a.note, a.slug  # sin canal, el motivo queda escrito
        for ch in a.channels:
            assert ch.channel == "web" or ch.verified in registry.VERIFIED_BY


@pytest.mark.parametrize(
    "body,msg",
    [
        ("- {slug: x, name: X, full_name: X, homepage: h, channels: [{channel: x}]}", "canal invalido"),
        ("- {slug: x, name: X, full_name: X, homepage: h, channels: [{channel: web}]}", "necesita url"),
        (
            "- {slug: x, name: X, full_name: X, homepage: h, channels: [{channel: telegram, handle: t}]}",
            "como se verifico",
        ),
        (
            "- {slug: x, name: X, full_name: X, homepage: h, channels: [{channel: bluesky}]}",
            "necesita handle",
        ),
        ("- {slug: x, name: X, full_name: X, homepage: h}", "anotar el motivo"),
        ("- {slug: x, name: X, homepage: h}", "sin 'full_name'"),
    ],
)
def test_invalid_political_registry(tmp_path: Path, body, msg):
    (tmp_path / "es.yaml").write_text(f"country: ES\nactors:\n  {body}\n", encoding="utf-8")
    with pytest.raises(RegistryError, match=msg):
        registry.load_political(tmp_path)
    (tmp_path / "es.yaml").write_text("country: ZZ\nactors: []\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="countries.yaml"):
        registry.load_political(tmp_path)


def test_dates_are_utc():
    assert political.parse_rss(RSS)[0]["published_at"] == datetime(2026, 10, 18, 10, tzinfo=UTC)
    assert json.dumps(BSKY)


def _entity(qid, web, **props):
    claims = {"P856": [{"mainsnak": {"datavalue": {"value": web}}}]}
    for p, v in props.items():
        claims[p] = [
            {"mainsnak": {"datavalue": {"value": v}}},
            {"rank": "deprecated", "mainsnak": {"datavalue": {"value": "viejo"}}},
        ]
    return {"entities": {qid: {"claims": claims}}}


@respx.mock
def test_wikidata_matches_only_the_official_website_and_stops_on_429(monkeypatch):
    from truthnews.crawler import wikidata

    respx.get("https://www.wikidata.org/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url__startswith="https://www.wikidata.org/w/api.php").mock(
        side_effect=[
            httpx.Response(200, json={"search": [{"id": "Q1"}, {"id": "Q2"}]}),
            httpx.Response(429),
        ]
    )
    respx.get("https://www.wikidata.org/wiki/Special:EntityData/Q1.json").mock(
        return_value=httpx.Response(200, json=_entity("Q1", "https://homonimo.test"))
    )
    respx.get("https://www.wikidata.org/wiki/Special:EntityData/Q2.json").mock(
        return_value=httpx.Response(
            200, json=_entity("Q2", "http://partido.test/", P12361="partido.test", P3789="canal")
        )
    )
    actors = [ACTORS[0], ACTORS[1]]
    settings = Settings(database_url="sqlite://", per_domain_delay_seconds=0)
    monkeypatch.setattr(wikidata, "_DONE", False)
    out = wikidata.run_once(settings, actors)
    assert out["a"] == {"qid": "Q2", "bluesky": ["partido.test"], "telegram": ["canal"]}
    assert out["_parado"] == "b: HTTP 429" and "b" not in out
    assert wikidata.run_once(settings, actors) is None  # una vez por proceso
    assert wikidata.host("www.Partido.test/x") == "partido.test"


def test_political_run_survives_wikidata_errors(session, monkeypatch):
    from truthnews.crawler import wikidata

    def boom(settings, actors):
        raise RuntimeError("caido")

    monkeypatch.setattr(wikidata, "run_once", boom)
    out = political.run(session, Settings(database_url="sqlite://"), [], wikidata=True)
    assert out["channels"] == 0 and "wikidata" not in out


@respx.mock
def test_wikidata_stops_and_says_why_when_robots_forbids(monkeypatch):
    from truthnews.crawler import wikidata

    respx.get("https://www.wikidata.org/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /w/\n")
    )
    monkeypatch.setattr(wikidata, "_DONE", False)
    out = wikidata.run_once(Settings(database_url="sqlite://", per_domain_delay_seconds=0), [ACTORS[0]])
    assert out == {"_parado": "a: robots.txt lo prohibe"}


ARTICLE = (
    "<html><head><title>Nota</title></head><body><nav>Inicio | Prensa</nav><article><h1>Nota de prensa</h1>"
    + "".join(
        f"<p>El paro se situa en el 10,6 % segun los ultimos datos, y el partido propone la medida {i} para "
        "seguir reduciendolo en los proximos meses con un plan de empleo para jovenes y parados.</p>"
        for i in range(6)
    )
    + "</article><footer>Aviso legal</footer></body></html>"
)
NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)


def _web(session, url, hours_ago=1, channel="web"):
    st = PoliticalStatement(
        actor="a",
        country="ES",
        channel=channel,
        url=url,
        url_hash=hashlib.sha256(url.encode()).hexdigest(),
        text="Nota de prensa",
        published_at=NOW - timedelta(hours=hours_ago),
    )
    session.add(st)
    session.flush()
    return st


@respx.mock
def test_bodies_once_with_caps_robots_and_a_403_that_stops_the_domain(session):
    for host in ("partido.test", "cerrado.test", "vacio.test"):
        respx.get(f"https://{host}/robots.txt").mock(return_value=httpx.Response(404))
    respx.get("https://prohibido.test/robots.txt").mock(
        return_value=httpx.Response(200, text="User-agent: *\nDisallow: /")
    )
    page = respx.get(url__startswith="https://partido.test/n").mock(
        return_value=httpx.Response(200, text=ARTICLE)
    )
    closed = respx.get(url__startswith="https://cerrado.test/n").mock(return_value=httpx.Response(403))
    respx.get("https://vacio.test/n1").mock(return_value=httpx.Response(200, text="<html></html>"))
    ok = [_web(session, f"https://partido.test/n{i}", hours_ago=i + 1) for i in range(4)]  # 4 > 3 por dominio
    shut = [_web(session, f"https://cerrado.test/n{i}") for i in range(2)]
    empty = _web(session, "https://vacio.test/n1")
    banned = _web(session, "https://prohibido.test/n1")
    social = _web(session, "https://t.me/canal/1", channel="telegram")
    old = _web(session, "https://partido.test/viejo", hours_ago=24 * 31)
    settings = Settings(database_url="sqlite://", per_domain_delay_seconds=0)

    out = political.fetch_bodies(session, settings, now=NOW)
    assert out == {"intentos": 6, "ok": 3, "estados": {"http 403": 1, "vacio": 1, "robots": 1}}
    assert page.call_count == 3 and closed.call_count == 1  # el 403 para el dominio en el acto
    assert all(st.body_status == "ok" and "10,6 %" in st.body for st in ok[:3])
    assert ok[0].body_fetched_at is not None and "Aviso legal" not in ok[0].body  # solo el cuerpo
    assert ok[3].body_status is None  # el cuarto del mismo dominio, en el siguiente ciclo
    assert sorted(s.body_status or "-" for s in shut) == ["-", "http 403"]  # el otro, sin intento
    assert all(s.body is None for s in shut)
    assert empty.body_status == "vacio" and banned.body_status == "robots"
    assert social.body_status is None and old.body_status is None  # solo web y solo la ventana

    # Siguiente ciclo: el cuarto de partido.test; cerrado.test no se vuelve a pedir en 24 h.
    again = political.fetch_bodies(session, settings, now=NOW + timedelta(minutes=30))
    assert again["intentos"] == 1 and ok[3].body_status == "ok" and closed.call_count == 1
    assert political.fetch_bodies(session, settings, now=NOW + timedelta(hours=1))["intentos"] == 0
    later = political.fetch_bodies(session, settings, now=NOW + timedelta(hours=25))
    assert later["estados"] == {"http 403": 1} and closed.call_count == 2
    assert [s.body_status for s in shut] == ["http 403", "http 403"]


@respx.mock
def test_bodies_respect_the_cycle_cap_and_survive_a_dead_page(session):
    respx.get("https://partido.test/robots.txt").mock(return_value=httpx.Response(404))
    respx.get(url__startswith="https://partido.test/n").mock(side_effect=httpx.ConnectError("x"))
    rows = [_web(session, f"https://partido.test/n{i}") for i in range(3)]
    settings = Settings(database_url="sqlite://", per_domain_delay_seconds=0)
    out = political.fetch_bodies(session, settings, now=NOW, limit=2)
    assert out == {"intentos": 2, "ok": 0, "estados": {"error ConnectErr": 2}}
    assert sum(r.body_status is None for r in rows) == 1
