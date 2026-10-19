"""Panel de administracion: balance de la operacion e investigaciones (Fase 3, criterio C8).

Protegido con HTTP Basic (ADMIN_USER / ADMIN_PASSWORD). Sin ADMIN_PASSWORD el panel no se abre.
Los formularios llevan un token derivado de la contrasena para evitar CSRF.
"""

# Sin `from __future__ import annotations`: FastAPI resuelve los alias Annotated locales al definir.

import hashlib
import hmac
import secrets
from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from truthnews.analysis import pipeline
from truthnews.config import Settings
from truthnews.models import (
    AdminAction,
    Article,
    Claim,
    CrawlRun,
    Feed,
    Investigation,
    Outlet,
    Piece,
    Story,
    Verification,
    utcnow,
)
from truthnews.social import queue as social_queue

security = HTTPBasic(auto_error=False)


def csrf_token(settings: Settings) -> str:
    return hmac.new(settings.admin_password.encode(), b"truthnews-admin-csrf", hashlib.sha256).hexdigest()


def text_coverage(session: Session, hours: int = 24) -> list[dict]:
    """Articulos de las ultimas `hours` horas con texto completo, por seccion (mide el relleno de textos)."""
    since = utcnow() - timedelta(hours=hours)
    rows = session.execute(
        select(Article.category, func.count(Article.id), func.count(Article.content_text))
        .where(Article.published_at >= since)
        .group_by(Article.category)
    ).all()
    out = [
        {"category": cat, "total": n, "with_text": t, "pct": round(100 * t / n, 1) if n else 0.0}
        for cat, n, t in rows
    ]
    return sorted(out, key=lambda r: (-r["total"], r["category"]))


def balance(session: Session) -> dict:
    since = utcnow() - timedelta(days=7)
    runs = list(session.scalars(select(CrawlRun).order_by(CrawlRun.id.desc()).limit(10)))
    failing = list(
        session.scalars(select(Feed).where(Feed.error_count > 0).order_by(Feed.error_count.desc()))
    )
    active_ids = set(
        session.scalars(select(Article.outlet_id).where(Article.published_at >= since).distinct())
    )
    silent = [
        o
        for o in session.scalars(select(Outlet).where(Outlet.active.is_(True)).order_by(Outlet.name))
        if o.id not in active_ids
    ]
    by_outlet = session.execute(
        select(Outlet.name, Verification.verdict, func.count())
        .join(Claim, Claim.outlet_id == Outlet.id)
        .join(Verification, Verification.claim_id == Claim.id)
        .group_by(Outlet.name, Verification.verdict)
        .order_by(Outlet.name)
    ).all()
    record: dict[str, dict[str, int]] = {}
    for name, verdict, n in by_outlet:
        record.setdefault(name, {})[verdict] = n
    pieces = list(session.scalars(select(Piece).order_by(Piece.created_at.desc()).limit(50)))
    tokens_out = sum((p.usage or {}).get("output_tokens") or 0 for p in pieces)
    return {
        "articles": session.scalar(select(func.count(Article.id))) or 0,
        "articles_week": session.scalar(select(func.count(Article.id)).where(Article.published_at >= since))
        or 0,
        "stories_multi": session.scalar(select(func.count(Story.id)).where(Story.n_outlets >= 2)) or 0,
        "claims": session.scalar(select(func.count(Claim.id))) or 0,
        "text_coverage": text_coverage(session),
        "runs": runs,
        "failing": failing,
        "silent": silent,
        "record": record,
        "pieces_revision": [p for p in pieces if p.status == "revision"],
        "pieces_published": sum(1 for p in pieces if p.status == "publicada"),
        "ai_output_tokens": tokens_out,
        "admin_actions": list(session.scalars(select(AdminAction).order_by(AdminAction.at.desc()).limit(20))),
        "investigations": list(
            session.scalars(select(Investigation).order_by(Investigation.created_at.desc()).limit(30))
        ),
    }


def make_router(settings: Settings, get_session, templates, render, on_change=lambda: None) -> APIRouter:
    # on_change: se llama tras retirar o restituir un veredicto (vacia las vistas en cache, p. ej. /hoy).
    router = APIRouter(prefix="/admin")

    def require_admin(credentials: Annotated[HTTPBasicCredentials | None, Depends(security)]) -> str:
        if not settings.admin_password:
            raise HTTPException(503, "Panel desactivado: configure ADMIN_PASSWORD")
        ok = (
            credentials is not None
            and secrets.compare_digest(credentials.username, settings.admin_user)
            and secrets.compare_digest(credentials.password, settings.admin_password)
        )
        if not ok:
            raise HTTPException(401, "Credenciales requeridas", headers={"WWW-Authenticate": "Basic"})
        return credentials.username

    Admin = Annotated[str, Depends(require_admin)]
    SessionDep = Annotated[Session, Depends(get_session)]

    @router.get("", response_class=HTMLResponse)
    def dashboard(request: Request, _: Admin, session: SessionDep):
        return render(
            request,
            "admin.html",
            b=balance(session),
            social=social_queue.status(session),
            csrf=csrf_token(settings),
        )

    @router.post("/verificacion/{verification_id}/retirar")
    def retire_verdict(
        verification_id: int,
        user: Admin,
        session: SessionDep,
        reason: Annotated[str, Form()],
        csrf: Annotated[str, Form()],
    ):
        """Retira un veredicto con nota publica y registra quien, cuando y por que (ADR 0049)."""
        if not hmac.compare_digest(csrf, csrf_token(settings)):
            raise HTTPException(403, "Token CSRF invalido")
        reason = " ".join(reason.split())
        if not 10 <= len(reason) <= 500:
            raise HTTPException(422, "El motivo debe tener entre 10 y 500 caracteres")
        ver = session.get(Verification, verification_id)
        if ver is None:
            raise HTTPException(404, "Veredicto no encontrado")
        pipeline.retire(session, ver, user, reason)
        session.commit()
        on_change()
        return RedirectResponse(f"/verificacion/{ver.claim_id}", status_code=303)

    @router.post("/verificacion/{verification_id}/restituir")
    def restore_verdict(
        verification_id: int,
        user: Admin,
        session: SessionDep,
        reason: Annotated[str, Form()],
        csrf: Annotated[str, Form()],
    ):
        """Deshace una retirada manual con su propio registro; el siguiente ciclo lo vuelve a juzgar."""
        if not hmac.compare_digest(csrf, csrf_token(settings)):
            raise HTTPException(403, "Token CSRF invalido")
        reason = " ".join(reason.split())
        if not 10 <= len(reason) <= 500:
            raise HTTPException(422, "El motivo debe tener entre 10 y 500 caracteres")
        ver = session.get(Verification, verification_id)
        if ver is None:
            raise HTTPException(404, "Veredicto no encontrado")
        try:
            pipeline.restore(session, ver, user, reason)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        session.commit()
        on_change()
        return RedirectResponse(f"/verificacion/{ver.claim_id}", status_code=303)

    @router.post("/investigaciones")
    def create_investigation(
        _: Admin, session: SessionDep, question: Annotated[str, Form()], csrf: Annotated[str, Form()]
    ):
        if not hmac.compare_digest(csrf, csrf_token(settings)):
            raise HTTPException(403, "Token CSRF invalido")
        question = question.strip()
        if not 10 <= len(question) <= 500:
            raise HTTPException(422, "La pregunta debe tener entre 10 y 500 caracteres")
        session.add(Investigation(question=question, country=settings.default_country))
        session.commit()
        return RedirectResponse("/admin", status_code=303)

    return router
