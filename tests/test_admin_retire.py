from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from truthnews.analysis import pipeline
from truthnews.analysis.verify import METHOD_VERSION
from truthnews.config import Settings
from truthnews.models import AdminAction, Article, Claim, Evidence, Outlet, Verification
from truthnews.web.admin import csrf_token
from truthnews.web.app import create_app

NOW = datetime.now(UTC)
AUTH = ("admin", "secreto")


@pytest.fixture
def admin_client(engine):
    return TestClient(create_app(Settings(database_url="sqlite://", admin_password="secreto"), engine=engine))


@pytest.fixture
def falso(session):
    """Caso real (Infobae, 19/10/2026): paro de EEUU juzgado contra Argentina."""
    o = Outlet(
        slug="infobae",
        name="Infobae",
        homepage="https://infobae.com",
        country="AR",
        language="es",
        scope="national",
    )
    session.add(o)
    session.flush()
    a = Article(
        outlet_id=o.id,
        url="https://infobae.com/x",
        url_hash="9" * 64,
        title="Las midterms del 3 de noviembre",
        published_at=NOW,
        language="es",
        country="AR",
        category="internacional",
    )
    session.add(a)
    session.flush()
    c = Claim(
        article_id=a.id,
        outlet_id=o.id,
        text="El desempleo se mantiene relativamente bajo, en torno al 4,2 %.",
        indicator="paro",
        geo="AR",
        value=4.2,
        unit="pct",
        extractor="ia",
    )
    session.add(c)
    session.flush()
    v = Verification(claim_id=c.id, verdict="falso", confidence=0.8, explanation="x", method="nivel/v10")
    v.evidence.append(Evidence(source="worldbank", label="Paro", url="https://wb", period="2025", value=7.1))
    session.add(v)
    session.commit()
    return v


def test_retire_requires_credentials_csrf_and_a_reason(admin_client, falso):
    url = f"/admin/verificacion/{falso.id}/retirar"
    ok = {"reason": "Paro de EEUU, no de Argentina.", "csrf": csrf_token(Settings(admin_password="secreto"))}
    assert admin_client.post(url, data=ok).status_code == 401
    assert admin_client.post(url, data={**ok, "csrf": "x"}, auth=AUTH).status_code == 403
    assert admin_client.post(url, data={**ok, "reason": "corto"}, auth=AUTH).status_code == 422
    assert admin_client.post("/admin/verificacion/999/retirar", data=ok, auth=AUTH).status_code == 404


def test_retire_publishes_the_note_and_records_who_when_why(admin_client, session, falso):
    token = csrf_token(Settings(admin_password="secreto"))
    reason = "La cifra es el paro de Estados Unidos, no el de Argentina."
    r = admin_client.post(
        f"/admin/verificacion/{falso.id}/retirar",
        data={"reason": reason, "csrf": token},
        auth=AUTH,
        follow_redirects=False,
    )
    assert r.status_code == 303 and r.headers["location"] == f"/verificacion/{falso.claim_id}"
    session.expire_all()
    v = session.get(Verification, falso.id)
    assert v.verdict == "sin-datos" and v.method == f"retirada-manual/{METHOD_VERSION}"
    assert f"[Retirado el {NOW:%d/%m/%Y}: {reason}]" in v.explanation and not v.evidence
    act = session.scalars(select(AdminAction)).one()
    assert (act.user, act.action, act.target, act.reason, act.before) == (
        "admin",
        "retirar-veredicto",
        f"verification:{falso.id}",
        reason,
        "falso",
    )
    page = admin_client.get("/admin", auth=AUTH).text
    assert "Retirar un veredicto" in page and reason in page
    assert "Retirado el" in admin_client.get(f"/verificacion/{falso.claim_id}").text


def test_reverify_does_not_undo_a_manual_retirement(session, falso):
    pipeline.retire(session, falso, "admin", "Motivo de prueba suficiente.")
    session.commit()
    assert pipeline.reverify_outdated(session) == {}  # ni con otra version del metodo
    assert session.get(Verification, falso.id).verdict == "sin-datos"


def test_restore_undoes_a_retirement_with_its_own_record(admin_client, session, falso):
    token = csrf_token(Settings(admin_password="secreto"))
    url = f"/admin/verificacion/{falso.id}/restituir"
    ok = {"reason": "Retirada por error: la cifra era de Argentina.", "csrf": token}
    assert admin_client.post(url, data=ok, auth=AUTH).status_code == 409  # no estaba retirado
    pipeline.retire(session, falso, "admin", "La cifra es el paro de Estados Unidos.")
    session.commit()
    r = admin_client.post(url, data=ok, auth=AUTH, follow_redirects=False)
    assert r.status_code == 303
    session.expire_all()
    v = session.get(Verification, falso.id)
    assert v.method == pipeline.RESTORED and "[Restituido el" in v.explanation
    acts = [(a.action, a.before) for a in session.scalars(select(AdminAction).order_by(AdminAction.id))]
    assert acts == [("retirar-veredicto", "falso"), ("restituir-veredicto", "sin-datos")]
    assert pipeline.reverify_outdated(session) != {}  # el siguiente re-juicio lo recoge
    v = session.get(Verification, falso.id)
    assert "[Retirado el" in v.explanation and "[Restituido el" in v.explanation  # notas a la vista


def test_the_retirement_reason_is_visible_in_the_public_pages(admin_client, session, falso):
    reason = "La cifra es el paro de Estados Unidos, no el de Argentina."
    pipeline.retire(session, falso, "admin", reason)
    session.commit()
    for path in ("/verificaciones", f"/verificacion/{falso.claim_id}"):
        html = admin_client.get(path).text
        assert 'class="vretired"' in html and "Retirado por la redacción" in html and reason in html


def test_retire_clears_the_cached_today_page(admin_client, falso):
    link = f'href="/verificacion/{falso.claim_id}"'
    assert link in admin_client.get("/hoy").text  # queda en cache (5 min)
    token = csrf_token(Settings(admin_password="secreto"))
    reason = "La cifra es el paro de Estados Unidos, no el de Argentina."
    admin_client.post(
        f"/admin/verificacion/{falso.id}/retirar", data={"reason": reason, "csrf": token}, auth=AUTH
    )
    assert link not in admin_client.get("/hoy").text  # la retirada vacia la cache: no sigue publicada
