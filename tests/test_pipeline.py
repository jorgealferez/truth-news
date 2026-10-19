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
    assert again == {"articles": 4, "stories_created": 0, "stories_updated": 2, "stories_relaunched": 0}
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


def test_reverify_outdated_methods_and_note_corrections(session, world):
    pipeline.assign_stories(session)
    pipeline.verify_claims(session, NOW - timedelta(days=1), fake_verifier(10.0))
    ver = session.scalars(select(Verification)).one()
    assert ver.verdict == "falso" and ver.method.endswith("/v7")
    assert pipeline.reverify_outdated(session, fake_verifier(12.5)) == {}  # ya en la version vigente
    ver.method = "nivel"  # veredicto de la version anterior del metodo
    session.flush()
    assert pipeline.reverify_outdated(session, fake_verifier(12.5)) == {"falso->verdadero": 1}
    assert ver.verdict == "verdadero" and "Corregido el" in ver.explanation and len(ver.evidence) == 1
    # Una afirmacion que ya no es atribuible con las reglas vigentes se retira con nota publica.
    ver.claim.text = "Canadá tiene una tasa de paro que se sitúa en el 12,5 %."
    ver.method = "nivel/v2"
    session.flush()
    assert pipeline.reverify_outdated(session, fake_verifier(12.5)) == {"verdadero->sin-datos": 1}
    assert ver.method.startswith("retirada/") and "retirada" in ver.explanation and not ver.evidence


def test_run_and_c6_invariant(session, world, monkeypatch):
    assert pipeline.run(session, NOW - timedelta(days=1), fake_verifier(12.5))["verdicts"] == {"verdadero": 1}
    assert session.scalars(select(Verification)).one().evidence

    class Bad(Verifier):
        def judge(self, claim):
            return Result("verdadero", 1.0, "sin pruebas", "x", [])

    session.query(Claim).delete()
    with pytest.raises(AssertionError, match="C6"):
        pipeline.verify_claims(session, NOW - timedelta(days=1), Bad())


def test_foreign_news_needs_an_explicit_territory(session, world):
    # Caso real: ABC, Internacional, 19/10/2026, sobre Pakistan. La frase no nombra pais.
    a = session.scalars(select(Article)).first()
    a.title, a.category = "Nueva polémica en la toma de poder en Pakistán", "economia"
    a.summary = "La inflación se situó en el 10,3 % interanual en septiembre."
    session.flush()
    assert pipeline.default_geo_of(a) == "XX"
    a.title, a.category = "La economía sigue estancada", "internacional"
    assert pipeline.default_geo_of(a) == "XX"
    a.category = "economia"
    assert pipeline.default_geo_of(a) == "ES"
    a.category = "internacional"
    out = pipeline.verify_claims(session, NOW - timedelta(days=1), fake_verifier(3.9))
    assert out["claims"] == 0
