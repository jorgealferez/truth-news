"""Aplicacion FastAPI: portada, secciones, paises, comunidades, medios y noticia."""
# Sin `from __future__ import annotations`: FastAPI resuelve los alias Annotated locales al definir.

import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session

from truthnews import registry
from truthnews.analysis.compare import QUALIFIER_LABEL, compare
from truthnews.config import Settings, get_settings
from truthnews.db import get_engine, session_factory
from truthnews.models import Article, Investigation, Outlet, Story, Thread, Topic
from truthnews.web import admin, queries, social

HERE = Path(__file__).resolve().parent
SITEMAP_DAYS = 90


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


def story_outlets(arts: list, comp, claims: list) -> list[dict]:
    """Una ficha por medio: su ultimo titular y lo que lo distingue ('como lo cuenta cada uno')."""
    verdicts: dict[str, list[str]] = {}
    for c in claims:
        verdicts.setdefault(c.outlet.name, []).append(c.verification.verdict)
    latest: dict[str, object] = {}
    for a in arts:
        latest[a.outlet.name] = a  # arts va en orden de publicacion
    out = []
    for name, a in latest.items():
        out.append(
            {
                "article": a,
                "outlet": a.outlet,
                "blame": comp.blame.get(name, []),
                "loaded": comp.loaded.get(name, []),
                "omits": comp.omissions.get(name, []),
                "verdicts": verdicts.get(name, []),
                "figures": {n: f for n, figs in comp.disputes.items() for f in figs if f.outlet == name},
            }
        )
    # Primero los medios con algo que marcar.
    out.sort(key=lambda o: -(len(o["blame"]) + len(o["omits"]) + len(o["loaded"]) + 2 * len(o["verdicts"])))
    return out


def spread(arts: list) -> dict:
    """Como se extendio la historia: primer medio y posicion relativa (0-100) de cada publicacion."""
    if not arts:
        return {}
    first, last = arts[0].published_at, arts[-1].published_at
    total = (last - first).total_seconds() or 1.0
    seen: set[str] = set()
    dots = []
    for a in arts:
        if a.outlet.name in seen:
            continue
        seen.add(a.outlet.name)
        dots.append(
            {"name": a.outlet.name, "pos": round(100 * (a.published_at - first).total_seconds() / total)}
        )
    return {"first": arts[0], "hours": round(total / 3600), "dots": dots}


def share_text(st, comp) -> str:
    """Texto para compartir: el titular y, si la hay, la diferencia mas llamativa."""
    for d in comp.dispute_summaries()[:1]:
        low, high = f"{d.low:,.0f}".replace(",", "."), f"{d.high:,.0f}".replace(",", ".")
        return f"{st.title} — {d.noun}: de {low} a {high} según el medio"
    return f"{st.title} — cómo lo cuentan {len(comp.outlets)} medios"


def create_app(settings: Settings | None = None, engine: Engine | None = None) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or get_engine(settings.database_url)
    make_session = session_factory(engine)
    app = FastAPI(title=settings.site_name, docs_url="/api/docs", redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["ago"] = _ago
    templates.env.filters["num"] = lambda v: f"{v:,.0f}".replace(",", ".")
    templates.env.filters["qual"] = lambda q: QUALIFIER_LABEL.get(q, q)
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

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(HERE / "static" / "favicon.ico", media_type="image/x-icon")

    @app.get("/site.webmanifest", include_in_schema=False)
    def manifest():
        return JSONResponse(
            {
                "name": settings.site_name,
                "short_name": settings.site_name,
                "description": registry.t(settings.default_language, "tagline"),
                "start_url": "/",
                "display": "standalone",
                "background_color": "#fbfaf6",
                "theme_color": "#14161b",
                "icons": [
                    {"src": "/static/icon-192.png", "sizes": "192x192", "type": "image/png"},
                    {"src": "/static/icon-512.png", "sizes": "512x512", "type": "image/png"},
                ],
            },
            media_type="application/manifest+json",
        )

    @app.get("/robots.txt", include_in_schema=False)
    def robots():
        return PlainTextResponse(
            f"User-agent: *\nDisallow: /admin\nDisallow: /api/\nSitemap: {settings.site_url}/sitemap.xml\n"
        )

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap(session: SessionDep):
        base = settings.site_url
        since = datetime.now(UTC) - timedelta(days=SITEMAP_DAYS)
        urls: list[tuple[str, datetime | None]] = [
            (f"{base}{p}", None)
            for p in (
                "/",
                "/contrastes",
                "/analisis",
                "/verificaciones",
                "/medios",
                "/investigaciones",
                "/metodologia",
                "/acerca",
            )
        ]
        urls += [(f"{base}/seccion/{c}", None) for c in registry.categories()]
        urls += [(f"{base}/pais/{c}", None) for c in registry.countries()]
        urls += [(f"{base}/medio/{slug}", None) for slug in session.scalars(select(Outlet.slug))]
        urls += [
            (f"{base}/historia/{sid}", last)
            for sid, last in session.execute(
                select(Story.id, Story.last_seen)
                .where(Story.n_outlets >= 2, Story.last_seen >= since)
                .order_by(Story.last_seen.desc())
                .limit(40_000)
            )
        ]
        urls += [
            (f"{base}/tema/{tid}", up) for tid, up in session.execute(select(Topic.id, Topic.updated_at))
        ]
        urls += [
            (f"{base}/hilo/{hid}", up)
            for hid, up in session.execute(
                select(Thread.id, Thread.updated_at).where(Thread.status == "publicado")
            )
        ]
        urls += [
            (f"{base}/investigacion/{iid}", up)
            for iid, up in session.execute(
                select(Investigation.id, Investigation.updated_at).where(Investigation.status == "publicada")
            )
        ]
        return Response(social.sitemap_xml(urls), media_type="application/xml")

    @app.get("/rss.xml", include_in_schema=False)
    def rss(session: SessionDep):
        items = [
            {
                "title": st.title,
                "link": f"{settings.site_url}/historia/{st.id}",
                "description": f"{st.n_outlets} medios"
                + (
                    f" · cifras en disputa: {', '.join(st.contrast['disputas'])}"
                    if (st.contrast or {}).get("disputas")
                    else ""
                ),
                "date": st.last_seen if st.last_seen.tzinfo else st.last_seen.replace(tzinfo=UTC),
            }
            for st in queries.top_stories(session, country=settings.default_country, limit=40)
        ]
        items += [
            {
                "title": p.title,
                "link": f"{settings.site_url}/tema/{p.topic_id}",
                "description": p.dek or "",
                "date": p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=UTC),
            }
            for p in queries.latest_pieces(session, limit=20)
        ]
        items.sort(key=lambda i: i["date"], reverse=True)
        xml = social.rss_xml(
            settings.site_name, settings.site_url, registry.t(settings.default_language, "tagline"), items
        )
        return Response(xml, media_type="application/rss+xml")

    image_cache: dict[tuple, bytes] = {}

    @app.get("/og/historia/{story_id}.png", include_in_schema=False)
    def story_og(story_id: int, session: SessionDep):
        st = session.get(Story, story_id)
        if st is None:
            raise HTTPException(404)
        key = (st.id, st.updated_at, st.title)
        if key not in image_cache:
            arts = queries.story_articles(session, st.id)
            comp = compare(arts)
            verdicts = queries.verdict_counts(session, [st.id]).get(st.id, {})
            kicker = (
                f"{registry.category_name(st.category, settings.default_language)} · {st.n_outlets} medios"
            )
            disputes = [(d.noun, d.low, d.high, d.n_outlets) for d in comp.dispute_summaries()]
            if len(image_cache) > 500:
                image_cache.clear()
            image_cache[key] = social.story_image(
                st.title, kicker, disputes, verdicts, registry.t(settings.default_language, "tagline")
            )
        return Response(
            image_cache[key], media_type="image/png", headers={"Cache-Control": "public, max-age=3600"}
        )

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
            threads=queries.front_threads(session, ids),
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
        related = [
            r
            for r in queries.top_stories(session, country=st.country, category=st.category, limit=7)
            if r.id != st.id
        ][:6]
        comp = compare(arts)
        claims = queries.claims_for_story(session, st.id)
        return render(
            request,
            "story.html",
            st=st,
            arts=arts,
            comp=comp,
            claims=claims,
            related=related,
            thread=queries.thread_for_story(session, st.id),
            outlets_view=story_outlets(arts, comp, claims),
            share=social.share_links(f"{settings.site_url}/historia/{st.id}", share_text(st, comp)),
            spread=spread(arts),
        )

    @app.get("/hilo/{thread_id}", response_class=HTMLResponse)
    def thread(request: Request, thread_id: int, session: SessionDep):
        th = session.get(Thread, thread_id)
        if th is None or th.status != "publicado":
            raise HTTPException(404)
        sources = {s["id"]: s for s in th.sources}
        return render(request, "thread.html", th=th, c=th.content, sources=sources)

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

    @app.get("/investigaciones", response_class=HTMLResponse)
    def investigations(request: Request, session: SessionDep):
        items = list(
            session.scalars(
                select(Investigation)
                .where(Investigation.status == "publicada")
                .order_by(Investigation.updated_at.desc())
                .limit(50)
            )
        )
        return render(request, "investigations.html", items=items)

    @app.get("/investigacion/{inv_id}", response_class=HTMLResponse)
    def investigation(request: Request, inv_id: int, session: SessionDep):
        inv = session.get(Investigation, inv_id)
        if inv is None or inv.status != "publicada":
            raise HTTPException(404)
        return render(request, "investigation.html", inv=inv, r=inv.report)

    app.include_router(admin.make_router(settings, get_session, templates, render))

    return app
