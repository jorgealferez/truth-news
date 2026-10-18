from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from truthnews.analysis import pipeline
from truthnews.analysis.verify import Result, Verifier
from truthnews.data import Observation
from truthnews.models import Article, Claim, Evidence, Outlet, Story, Verification

NOW = datetime.now(UTC)


@pytest.fixture()
def world(session):
    outs = [
        Outlet(
            slug=f"m{i}",
            name=f"Medio {i}",
            homepage="https://m",
            country="ES",
            language="es",
            scope="national",
        )
        for i in range(3)
    ]
    session.add_all(outs)
    session.flush()

    def add(i, title, outlet, minutes, summary=""):
        a = Article(
            outlet_id=outs[outlet].id,
            url=f"https://m/{i}",
            url_hash=f"{i:064d}",
            title=title,
            summary=summary,
            published_at=NOW - timedelta(minutes=minutes),
            language="es",
            country="ES",
            category="economia",
            topics=[],
        )
        session.add(a)
        return a

    add(
        1,
        "El Gobierno aprueba la reforma de las pensiones en el Consejo de Ministros",
        0,
        50,
        "La tasa de paro se sitúa en el 12,5 % según el texto.",
    )
    add(2, "El Consejo de Ministros aprueba la reforma de las pensiones", 1, 40)
    add(3, "Aprobada la reforma de las pensiones en el Consejo de Ministros", 2, 30)
    add(4, "Un terremoto sacude Japón", 0, 20)
    session.flush()
    return outs


def fake_verifier(value=10.0):
    period = f"{NOW.year}-{NOW.month:02d}"
    return Verifier(
        lambda s, g, label: Observation("eurostat", label, "https://ec.europa.eu/x", period, value)
    )


def test_assign_stories_and_identity_is_kept(session, world):
    out = pipeline.assign_stories(session)
    assert out["stories_created"] == 2
    big = session.scalars(select(Story).where(Story.n_outlets == 3)).one()
    assert big.n_articles == 3 and big.category == "economia"
    again = pipeline.assign_stories(session)
    assert again == {"articles": 4, "stories_created": 0, "stories_updated": 2}
    assert session.scalar(select(func.count(Story.id))) == 2


def test_verify_claims_stores_evidence_and_is_idempotent(session, world):
    pipeline.assign_stories(session)
    since = NOW - timedelta(days=1)
    out = pipeline.verify_claims(session, since, fake_verifier())
    assert out == {"claims": 1, "verdicts": {"falso": 1}}
    c = session.scalars(select(Claim)).one()
    assert c.story_id is not None and c.verification.verdict == "falso"
    assert session.scalar(select(func.count(Evidence.id))) == 1
    assert pipeline.verify_claims(session, since, fake_verifier())["claims"] == 0


def test_run_and_c6_invariant(session, world, monkeypatch):
    assert pipeline.run(session, NOW - timedelta(days=1), fake_verifier(12.5))["verdicts"] == {"verdadero": 1}
    assert session.scalars(select(Verification)).one().evidence

    class Bad(Verifier):
        def judge(self, claim):
            return Result("verdadero", 1.0, "sin pruebas", "x", [])

    session.query(Claim).delete()
    with pytest.raises(AssertionError, match="C6"):
        pipeline.verify_claims(session, NOW - timedelta(days=1), Bad())
