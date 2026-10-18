"""Aplicacion FastAPI: portada, secciones, paises, comunidades, medios y noticia."""
# Sin `from __future__ import annotations`: FastAPI resuelve los alias Annotated locales al definir.

import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from truthnews import registry
from truthnews.analysis.compare import compare
from truthnews.config import Settings, get_settings
from truthnews.db import get_engine, session_factory
from truthnews.models import Article, Outlet, Story
from truthnews.web import queries

HERE = Path(__file__).resolve().parent


def _ago(value: datetime | None, lang: str = "es") -> str:
    if value is None:
        return ""
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    minutes = int((datetime.now(UTC) - value).total_seconds() // 60)
    if minutes < 60:
        return f"{max(minutes, 1)} min"
    if minutes < 60 * 24:
        return f"{minutes // 60} h"
    return value.strftime("%d/%m/%Y")


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or get_engine(settings.database_url)
    make_session = session_factory(engine)
    app = FastAPI(title=settings.site_name, docs_url="/api/docs", redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["ago"] = _ago
    templates.env.globals.update(
        site=settings,
        t=registry.t,
        category_name=registry.category_name,
        country_name=registry.country_name,
        region_name=registry.region_name,
        categories=list(registry.categories().keys()),
        countries=list(registry.countries().keys()),
        languages=registry.languages(),
    )

    def get_session():
        session = make_session()
        try:
            yield session
        finally:
            session.close()

    SessionDep = Annotated[Session, Depends(get_session)]
    PageQ = Annotated[int, Query(ge=1)]

    totals_cache: dict = {}

    def totals_cached(session: Session) -> dict:
        # Las cifras de cabecera cambian cada ciclo del worker (30 min): 60 s de cache bastan.
        now = time.monotonic()
        if not totals_cache or now - totals_cache["at"] > 60:
            totals_cache.update(at=now, value=queries.totals(session))
        return totals_cache["value"]

    def lang_of(request: Request) -> str:
        lang = request.query_params.get("lang") or request.cookies.get("lang") or settings.default_language
        return lang if lang in registry.languages() else settings.default_language

    def render(request: Request, name: str, **ctx) -> HTMLResponse:
        lang = lang_of(request)
        resp = templates.TemplateResponse(request, name, {"lang": lang, **ctx})
        if request.query_params.get("lang") == lang:
            resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
        return resp

    @app.get("/healthz")
    def healthz(session: SessionDep):
        session.execute(text("SELECT 1"))
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def home(request: Request, session: SessionDep):
        # Portada de contrastes: historias contadas por varios medios del pais por defecto.
        home_country = settings.default_country
        stories = queries.top_stories(session, country=home_country, limit=24)
        ids = [s.id for s in stories]
        wire = queries.latest(session, country=home_country, limit=12)
        return render(
            request,
            "home.html",
            stories=stories,
            outlet_names=queries.story_outlet_names(session, ids),
            verdicts=queries.verdict_counts(session, ids),
            wire=wire,
            totals=totals_cached(session),
            pieces=queries.latest_pieces(session, kind="analisis", limit=4),
        )

    @app.get("/analisis", response_class=HTMLResponse)
    def analyses(request: Request, session: SessionDep, page: PageQ = 1, tipo: str | None = None):
        kind = tipo if tipo in ("analisis", "opinion") else None
        pieces = queries.latest_pieces(session, kind=kind, limit=20, offset=(page - 1) * 20)
        return render(request, "analyses.html", pieces=pieces, page=page, tipo=kind)

    @app.get("/tema/{topic_id}", response_class=HTMLResponse)
    def topic(request: Request, topic_id: int, session: SessionDep):
        tp, pieces, stories = queries.topic_view(session, topic_id)
        if tp is None:
            raise HTTPException(404)
        synth = pieces["analisis"].synthesis if "analisis" in pieces else {}
        slugs = [m["medio_slug"] for m in synth.get("que_dice_cada_medio", [])]
        ids = [s.id for s in stories]
        return render(
            request,
            "topic.html",
            tp=tp,
            pieces=pieces,
            stories=stories,
            synth=synth,
            outlets=queries.outlets_by_slug(session, slugs),
            outlet_names=queries.story_outlet_names(session, ids),
            verdicts=queries.verdict_counts(session, ids),
        )

    @app.get("/verificaciones", response_class=HTMLResponse)
    def verifications(request: Request, session: SessionDep):
        return render(request, "verifications.html", claims=queries.all_verifications(session))

    @app.get("/historia/{story_id}", response_class=HTMLResponse)
    def story(request: Request, story_id: int, session: SessionDep):
        st = session.get(Story, story_id)
        if st is None:
            raise HTTPException(404)
        arts = queries.story_articles(session, st.id)
        return render(
            request,
            "story.html",
            st=st,
            arts=arts,
            comp=compare(arts),
            claims=queries.claims_for_story(session, st.id),
        )

    @app.get("/contrastes", response_class=HTMLResponse)
    def contrasts(request: Request, session: SessionDep, page: PageQ = 1, seccion: str | None = None):
        stories = queries.top_stories(
            session,
            country=settings.default_country,
            category=seccion,
            hours=24 * 7,
            limit=30,
            offset=(page - 1) * 30,
        )
        ids = [s.id for s in stories]
        return render(
            request,
            "contrasts.html",
            stories=stories,
            page=page,
            seccion=seccion,
            outlet_names=queries.story_outlet_names(session, ids),
            verdicts=queries.verdict_counts(session, ids),
        )

    @app.get("/metodologia", response_class=HTMLResponse)
    def methodology(request: Request):
        return render(request, "methodology.html")

    @app.get("/seccion/{slug}", response_class=HTMLResponse)
    def section(request: Request, slug: str, session: SessionDep, page: PageQ = 1):
        if slug not in registry.categories():
            raise HTTPException(404)
        items = queries.latest(session, category=slug, page=page)
        return render(
            request,
            "list.html",
            items=items,
            page=page,
            heading=registry.category_name(slug, lang_of(request)),
        )

    @app.get("/pais/{iso}", response_class=HTMLResponse)
    def country(request: Request, iso: str, session: SessionDep, page: PageQ = 1):
        iso = iso.upper()
        if iso not in registry.countries():
            raise HTTPException(404)
        items = queries.latest(session, country=iso, page=page)
        regions = registry.countries()[iso].get("regions", {})
        return render(
            request,
            "list.html",
            items=items,
            page=page,
            regions=regions,
            heading=registry.country_name(iso, lang_of(request)),
        )

    @app.get("/region/{code}", response_class=HTMLResponse)
    def region(request: Request, code: str, session: SessionDep, page: PageQ = 1):
        code = code.upper()
        iso = code.split("-")[0]
        if code not in registry.countries().get(iso, {}).get("regions", {}):
            raise HTTPException(404)
        items = queries.latest(session, region=code, page=page)
        return render(request, "list.html", items=items, page=page, heading=registry.region_name(code))

    @app.get("/medios", response_class=HTMLResponse)
    def outlets(request: Request, session: SessionDep, pais: str | None = None):
        return render(request, "outlets.html", rows=queries.outlets(session, pais.upper() if pais else None))

    @app.get("/medio/{slug}", response_class=HTMLResponse)
    def outlet(request: Request, slug: str, session: SessionDep, page: PageQ = 1):
        o = session.scalars(select(Outlet).where(Outlet.slug == slug)).first()
        if o is None:
            raise HTTPException(404)
        items = queries.latest(session, outlet_id=o.id, page=page)
        record = queries.verdict_counts(session, outlet_id=o.id).get("total", {})
        return render(request, "list.html", items=items, page=page, heading=o.name, outlet=o, record=record)

    @app.get("/noticia/{article_id}", response_class=HTMLResponse)
    def article(request: Request, article_id: int, session: SessionDep):
        a = session.get(Article, article_id)
        if a is None:
            raise HTTPException(404)
        related = [x for x in queries.latest(session, category=a.category, limit=8) if x.id != a.id][:6]
        return render(request, "article.html", a=a, related=related)

    @app.get("/acerca", response_class=HTMLResponse)
    def about(request: Request):
        return render(request, "about.html")

    @app.get("/idioma/{lang}")
    def set_lang(lang: str, request: Request):
        target = request.headers.get("referer") or "/"
        resp = RedirectResponse(target, status_code=303)
        if lang in registry.languages():
            resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
        return resp

    @app.get("/api/articles")
    def api_articles(
        session: SessionDep,
        category: str | None = None,
        country: str | None = None,
        region: str | None = None,
        page: PageQ = 1,
    ):
        items = queries.latest(
            session,
            category=category,
            country=country.upper() if country else None,
            region=region.upper() if region else None,
            page=page,
        )
        return JSONResponse(
            [
                {
                    "id": a.id,
                    "title": a.title,
                    "url": a.url,
                    "outlet": a.outlet.slug,
                    "category": a.category,
                    "country": a.country,
                    "region": a.region,
                    "published_at": a.published_at.isoformat(),
                }
                for a in items
            ]
        )

    return app
