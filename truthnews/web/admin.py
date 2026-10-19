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

from truthnews.config import Settings
from truthnews.models import (
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
        "runs": runs,
        "failing": failing,
        "silent": silent,
        "record": record,
        "pieces_revision": [p for p in pieces if p.status == "revision"],
        "pieces_published": sum(1 for p in pieces if p.status == "publicada"),
        "ai_output_tokens": tokens_out,
        "investigations": list(
            session.scalars(select(Investigation).order_by(Investigation.created_at.desc()).limit(30))
        ),
    }


def make_router(settings: Settings, get_session, templates, render) -> APIRouter:
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
