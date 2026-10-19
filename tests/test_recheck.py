"""Relectura del texto completo y cifras que cambian en el cuerpo (ADR 0052)."""

import asyncio
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import select

from truthnews.analysis.figure_changes import body_excerpts, for_outlet
from truthnews.crawler.extract import sha256
from truthnews.crawler.http import PoliteClient
from truthnews.crawler.ingest import recheck_texts
from truthnews.models import REVISION_MAX_CHARS, Article, ArticleRevision, Outlet

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)
FILLER = " ".join(f"Frase de relleno numero {w} sobre el pleno del Congreso." for w in range(12))
OLD = (
    f"{FILLER}\nEl Gobierno cifra en 12 los muertos por las lluvias en Valencia. La Aemet mantiene la alerta."
)
NEW = (
    f"{FILLER}\nEl Gobierno cifra en 15 los muertos por las lluvias en Valencia. La Aemet mantiene la alerta."
)


def page(text: str) -> str:
    paras = "".join(f"<p>{p}</p>" for p in text.split("\n"))
    return f"<html><head><title>t</title></head><body><article>{paras}</article></body></html>"


def _outlet(session) -> Outlet:
    o = Outlet(
        slug="m", name="Medio", homepage="https://m.test/", country="ES", language="es", scope="national"
    )
    session.add(o)
    session.flush()
    return o


def _article(session, o, n, text, published, **kw) -> Article:
    a = Article(
        outlet_id=o.id,
        url=f"https://m.test/politica/{n}",
        url_hash=f"r{n}".ljust(64, "0"),
        title=f"Lluvias {n}",
        published_at=published,
        fetched_at=kw.pop("fetched_at", published),
        language="es",
        country="ES",
        category=kw.pop("category", "politica"),
        content_text=text,
        content_hash=sha256(text) if text else None,
        **kw,
    )
    session.add(a)
    session.flush()
    return a


def _run(session, bodies: dict[str, str], now=NOW, limit=10, status=200):
    hits = []

    def handler(request):
        hits.append(request.url.path)
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        body = bodies.get(request.url.path)
        if body is None or status != 200:
            return httpx.Response(status if body is not None else 404)
        return httpx.Response(200, text=page(body), headers={"content-type": "text/html"})

    async def go():
        async with PoliteClient("ua", 0, transport=httpx.MockTransport(handler)) as client:
            return await recheck_texts(session, client, limit, now=now, run_id=None)

    return asyncio.run(go()), [h for h in hits if h != "/robots.txt"]


def test_body_excerpts_quote_only_the_changed_sentence_and_the_notice():
    assert body_excerpts(OLD, NEW) == (
        "El Gobierno cifra en 12 los muertos por las lluvias en Valencia.",
        "El Gobierno cifra en 15 los muertos por las lluvias en Valencia.",
    )
    told = NEW.replace(FILLER, "Actualizacion: el Gobierno eleva a 15 el numero de victimas.")
    before, after = body_excerpts(OLD, told)
    assert after.startswith("Actualizacion: el Gobierno eleva a 15") and "15 los muertos" in after
    assert body_excerpts(OLD, OLD.replace("mantiene", "prolonga")) is None  # sin cifra no hay revision
    long = "x " * 400 + "con 12 muertos."
    b, a = body_excerpts(f"Hoy hay 12 muertos. {long}", f"Hoy hay 14 muertos. {long}")
    assert len(b) <= REVISION_MAX_CHARS and len(a) <= REVISION_MAX_CHARS


def test_recheck_stores_a_content_revision_when_a_figure_changes(session):
    o = _outlet(session)
    changed = _article(session, o, 1, OLD, NOW - timedelta(hours=5))
    edited = _article(session, o, 2, OLD, NOW - timedelta(hours=5))
    same = _article(session, o, 3, OLD, NOW - timedelta(hours=5))
    out, hits = _run(
        session,
        {
            "/politica/1": NEW,
            "/politica/2": OLD.replace("mantiene", "prolonga"),
            "/politica/3": OLD,
        },
    )
    assert out == {"rechecked": 3, "changed": 2, "revisions": 1}
    rev = session.scalars(select(ArticleRevision)).one()
    assert rev.article_id == changed.id and rev.field == "content"
    assert "12 los muertos" in rev.before and "15 los muertos" in rev.after
    assert rev.before_hash == sha256(OLD) and rev.after_hash == changed.content_hash == sha256(NEW)
    assert "prolonga" in edited.content_text and same.content_hash == sha256(OLD)
    assert all(a.content_checks == 1 for a in (changed, edited, same))
    [fc] = for_outlet(session, o.id)
    assert (fc.field, fc.noun, fc.before, fc.after, fc.silent) == ("content", "muertos", 12, 15, True)


def test_recheck_picks_only_what_is_due_and_stops_after_two_reads(session):
    o = _outlet(session)
    fresh = _article(session, o, 1, OLD, NOW - timedelta(hours=1))  # aun no han pasado 3 h
    first = _article(session, o, 2, OLD, NOW - timedelta(hours=4))
    second = _article(session, o, 3, OLD, NOW - timedelta(hours=30), content_checks=1)
    done = _article(session, o, 4, OLD, NOW - timedelta(hours=30), content_checks=2)
    old = _article(session, o, 5, OLD, NOW - timedelta(hours=60))  # fuera de la ventana de 48 h
    sport = _article(session, o, 6, OLD, NOW - timedelta(hours=5), category="deportes")
    archived = _article(session, o, 7, OLD, NOW - timedelta(hours=5), origin="archivo")
    no_text = _article(session, o, 8, None, NOW - timedelta(hours=5))
    _, hits = _run(session, {"/politica/2": OLD, "/politica/3": OLD})
    assert sorted(hits) == ["/politica/2", "/politica/3"]
    assert (first.content_checks, second.content_checks, done.content_checks) == (1, 2, 2)
    assert all(a.content_checks == 0 for a in (fresh, old, sport, archived, no_text))
    _, again = _run(session, {"/politica/2": OLD, "/politica/3": OLD}, now=NOW + timedelta(hours=1))
    assert again == []  # first espera a las 24 h de publicarse; second ya tiene sus dos lecturas
    _, later = _run(session, {"/politica/1": OLD, "/politica/2": OLD}, now=NOW + timedelta(hours=21))
    assert sorted(later) == ["/politica/1", "/politica/2"]  # la primera de fresh y la segunda de first
    assert (fresh.content_checks, first.content_checks) == (1, 2)


def test_recheck_gives_up_on_a_failing_domain_and_counts_the_attempt(session):
    o = _outlet(session)
    arts = [_article(session, o, n, OLD, NOW - timedelta(hours=5)) for n in range(1, 5)]
    out, hits = _run(session, {f"/politica/{n}": NEW for n in range(1, 5)}, status=503)
    assert out == {"rechecked": 0, "changed": 0, "revisions": 0} and len(hits) == 2
    assert sum(a.content_checks for a in arts) == 2 and all(a.content_hash == sha256(OLD) for a in arts)
