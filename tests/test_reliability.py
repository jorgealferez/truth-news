from datetime import UTC, datetime, timedelta

from truthnews.analysis.reliability import (
    MIN_CHECKS,
    Record,
    blind_spots,
    history,
    missing_outlets,
    ranking,
    records,
    wilson_lower,
)
from truthnews.models import Article, Claim, Evidence, Outlet, Story, Verification

NOW = datetime(2026, 10, 19, 12, tzinfo=UTC)


def outlet(session, slug, country="ES", scope="national"):
    o = Outlet(
        slug=slug, name=slug.upper(), homepage="https://x", country=country, language="es", scope=scope
    )
    session.add(o)
    session.flush()
    return o


def article(session, o, n, story=None, hours=0):
    a = Article(
        outlet_id=o.id,
        url=f"https://x/{o.slug}/{n}",
        url_hash=f"{o.slug}-{n}".ljust(64, "_"),
        title=f"Titular {n}",
        published_at=NOW - timedelta(hours=hours),
        language="es",
        country=o.country,
        category="politica",
        topics=[],
        story_id=story.id if story else None,
    )
    session.add(a)
    session.flush()
    return a


def checked(session, o, verdicts):
    for i, verdict in enumerate(verdicts):
        a = article(session, o, f"c{i}")
        c = Claim(
            article_id=a.id,
            outlet_id=o.id,
            text="El paro es del 10 %",
            indicator="paro",
            geo="ES",
            value=10.0,
            unit="pct",
        )
        session.add(c)
        session.flush()
        v = Verification(
            claim_id=c.id,
            verdict=verdict,
            confidence=0.9,
            explanation="x",
            method="nivel",
            checked_at=NOW - timedelta(minutes=i),
        )
        v.evidence.append(
            Evidence(source="ine", label="Paro", url="https://ine.es", period="2026-T3", value=10.0)
        )
        session.add(v)
    session.flush()


def story(session, n_outlets, hours=0, country="ES"):
    s = Story(
        title=f"Historia {n_outlets}",
        category="politica",
        country=country,
        first_seen=NOW - timedelta(hours=hours + 1),
        last_seen=NOW - timedelta(hours=hours),
        n_articles=n_outlets,
        n_outlets=n_outlets,
    )
    session.add(s)
    session.flush()
    return s


def test_wilson_orders_by_evidence_not_by_luck():
    assert wilson_lower(0, 0) == 0.0
    assert wilson_lower(2, 2) < wilson_lower(40, 45)  # 2 de 2 no gana a 40 de 45
    assert 0.0 < wilson_lower(5, 10) < 0.5 < wilson_lower(10, 10) < 1.0


def test_records_ranking_and_history(session):
    a, b, c = outlet(session, "a"), outlet(session, "b"), outlet(session, "c")
    checked(session, a, ["verdadero"] * 9 + ["falso"])
    checked(session, b, ["verdadero"] * 2 + ["sin-datos"] * 4)  # 2 comprobadas: pocas
    checked(session, c, ["verdadero", "impreciso", "falso", "enganoso", "falso", "verdadero"])
    recs = {r.outlet.slug: r for r in records(session)}
    assert recs["b"].checked == 2 and not recs["b"].ranked and recs["b"].accuracy == 1.0
    assert recs["a"].shares() == [("verdadero", 9, 90), ("falso", 1, 10)]
    ranked, few = ranking(list(recs.values()))
    assert [r.outlet.slug for r in ranked] == ["a", "c"] and [r.outlet.slug for r in few] == ["b"]
    assert all(r.checked >= MIN_CHECKS for r in ranked)
    assert records(session, country="PT") == []
    h = history(session, a.id, limit=3)
    assert len(h) == 3 and h[0].verification.verdict == "verdadero" and h[0].verification.evidence
    assert Record(a).accuracy is None


def test_who_does_not_report_it(session):
    a, b, c = outlet(session, "a"), outlet(session, "b"), outlet(session, "c")
    outlet(session, "parado")  # no publico nada esos dias: no "omite"
    outlet(session, "regional", scope="regional")
    big, small = story(session, 6), story(session, 2)
    article(session, a, 1, big)
    article(session, b, 1, big)
    article(session, c, 1, small)
    assert [o.slug for o in missing_outlets(session, big)] == ["c"]
    bs = blind_spots(session, c, now=NOW)
    assert bs.big == 1 and [s.id for s in bs.missed] == [big.id] and bs.covered_share == 0
    assert blind_spots(session, a, now=NOW).covered_share == 100
    assert blind_spots(session, outlet(session, "nuevo"), now=NOW).big == 0
    assert blind_spots(session, a, now=NOW).missed == []


def test_pages_show_ranking_record_and_who_does_not_report_it(engine, session):
    from fastapi.testclient import TestClient

    from truthnews.config import Settings
    from truthnews.models import utcnow
    from truthnews.web.app import create_app

    now = utcnow()
    a, b, c = outlet(session, "a"), outlet(session, "b"), outlet(session, "c")
    checked(session, a, ["verdadero"] * 5 + ["falso"])
    checked(session, b, ["falso"])
    s = Story(
        title="Gran historia",
        category="politica",
        country="ES",
        first_seen=now - timedelta(hours=2),
        last_seen=now,
        n_articles=6,
        n_outlets=6,
    )
    session.add(s)
    session.flush()
    for o in (a, b):
        x = article(session, o, "h", s)
        x.published_at = now - timedelta(hours=1)
    y = article(session, c, "otra")
    y.published_at = now - timedelta(hours=1)
    session.commit()
    client = TestClient(create_app(Settings(database_url="sqlite://"), engine=engine))

    medios = client.get("/medios").text
    assert "Quién acierta con los datos" in medios and ">A</a>" in medios and "83 %" in medios
    assert "Medios con pocas verificaciones todavía (1)" in medios
    ficha = client.get("/medio/a").text
    assert "Fiabilidad comprobada" in ficha and "(5 de 6)" in ficha and "Historial de veredictos (6)" in ficha
    assert "Pocas verificaciones todavía" in client.get("/medio/b").text
    ficha_c = client.get("/medio/c").text
    assert "Aún no hemos comprobado" in ficha_c and "Contó el 0 % de las 1 historias grandes" in ficha_c
    page = client.get(f"/historia/{s.id}").text
    assert "Quién no lo cuenta" in page and 'href="/medio/c">C</a>' in page
    home = client.get("/").text
    assert "Quién acierta con los datos" in home and "/medio/a" in home
