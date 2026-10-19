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

from truthnews import ads as adsmod
from truthnews import registry
from truthnews.ai import translate
from truthnews.analysis import abroad
from truthnews.analysis.compare import QUALIFIER_LABEL, compare
from truthnews.config import Settings, get_settings
from truthnews.db import get_engine, session_factory
from truthnews.models import Article, Investigation, Outlet, Story, Thread, Topic
from truthnews.social import images
from truthnews.web import admin, citations, queries, seo, social, topicview

HERE = Path(__file__).resolve().parent
SITEMAP_DAYS = 90


def _dato(value: float | None, unit: str | None = None) -> str:
    """Un dato oficial legible: 10,0 % o 1.234,5 (es)."""
    if value is None:
        return "—"
    if unit == "pct":
        return f"{value:.1f}".replace(".", ",") + " %"
    text = f"{value:,.1f}" if value % 1 else f"{value:,.0f}"
    return text.replace(",", "_").replace(".", ",").replace("_", ".")


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


def investigation_title(inv) -> str:
    return (inv.report or {}).get("analisis", {}).get("titular") or inv.question


def create_app(
    settings: Settings | None = None,
    engine: Engine | None = None,
    ads_client: adsmod.AdsClient | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    ads_client = ads_client or adsmod.AdsClient(settings.ads_service_url, settings.ads_site_key)
    engine = engine or get_engine(settings.database_url)
    make_session = session_factory(engine)
    app = FastAPI(title=settings.site_name, docs_url="/api/docs", redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["ago"] = _ago
    templates.env.filters["num"] = lambda v: f"{v:,.0f}".replace(",", ".")
    templates.env.filters["qual"] = lambda q: QUALIFIER_LABEL.get(q, q)
    templates.env.filters["word_diff"] = citations.word_diff
    templates.env.filters["dato"] = _dato
    templates.env.globals.update(
        site=settings,
        t=registry.t,
        category_name=registry.category_name,
        country_name=registry.country_name,
        region_name=registry.region_name,
        categories=list(registry.categories().keys()),
        countries=list(registry.countries().keys()),
        languages=registry.languages(),
        url=seo.path,
        investigation_title=investigation_title,
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

    def canonical(request: Request, kind: str, ident: int, title: str | None):
        """301 a /<kind>/<id>-<slug> si se llego por otra forma (sin slug, slug viejo)."""
        want = seo.path(kind, ident, title)
        if request.url.path == want:
            return None
        query = request.url.query
        return RedirectResponse(want + (f"?{query}" if query else ""), status_code=301)

    def ref_id(ref: str) -> int:
        ident = seo.parse_ref(ref)
        if ident is None:
            raise HTTPException(404)
        return ident

    def render(request: Request, name: str, **ctx) -> HTMLResponse:
        lang = lang_of(request)
        resp = templates.TemplateResponse(request, name, {"lang": lang, "ads": {}, **ctx})
        if request.query_params.get("lang") == lang:
            resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
        return resp

    def ads_for(request: Request, slots, title: str, category, texts, country: str) -> dict:
        """Anuncios por el contenido de la pagina (ads-service); {} si no hay servicio o falla."""
        if not ads_client.enabled:
            return {}
        context = adsmod.page_context(
            f"{settings.site_url}{request.url.path}", title, category, texts, country, lang_of(request)
        )
        ip = adsmod.client_ip(request.headers, request.client.host if request.client else None)
        viewer = adsmod.viewer_hash(ip, request.headers.get("user-agent", ""))
        return ads_client.serve(slots, context, viewer)

    def list_ads(request: Request, heading: str, items, country: str, category=None) -> dict:
        texts = [a.title for a in items] + [a.summary or "" for a in items[:10]]
        return ads_for(request, ("list-native", "footer-strip"), heading, category, texts, country)

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
                    {
                        "src": "/static/icon-maskable-512.png",
                        "sizes": "512x512",
                        "type": "image/png",
                        "purpose": "maskable",
                    },
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
                "/publicidad",
                "/acerca",
            )
        ]
        urls += [(f"{base}/seccion/{c}", None) for c in registry.categories()]
        urls += [(f"{base}/pais/{c}", None) for c in registry.countries()]
        urls += [(f"{base}/medio/{slug}", None) for slug in session.scalars(select(Outlet.slug))]
        urls += [
            (base + seo.path("historia", sid, title), last)
            for sid, title, last in session.execute(
                select(Story.id, Story.title, Story.last_seen)
                .where(Story.n_outlets >= 2, Story.last_seen >= since)
                .order_by(Story.last_seen.desc())
                .limit(40_000)
            )
        ]
        topic_titles = queries.topic_titles(session)
        urls += [
            (base + seo.path("tema", tid, topic_titles.get(tid, title)), up)
            for tid, title, up in session.execute(select(Topic.id, Topic.title, Topic.updated_at))
        ]
        urls += [
            (base + seo.path("hilo", hid, title), up)
            for hid, title, up in session.execute(
                select(Thread.id, Thread.title, Thread.updated_at).where(Thread.status == "publicado")
            )
        ]
        urls += [
            (base + seo.path("investigacion", inv.id, investigation_title(inv)), inv.updated_at)
            for inv in session.scalars(select(Investigation).where(Investigation.status == "publicada"))
        ]
        return Response(social.sitemap_xml(urls), media_type="application/xml")

    @app.get("/rss.xml", include_in_schema=False)
    def rss(session: SessionDep):
        items = [
            {
                "title": st.title,
                "link": settings.site_url + seo.path("historia", st.id, st.title),
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
                "link": settings.site_url + seo.path("tema", p.topic_id, p.title),
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
            if len(image_cache) > 500:
                image_cache.clear()
            image_cache[key] = images.story_png(session, st, settings.default_language)
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
        wire = queries.latest_checks(session, limit=8)
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
            ads=ads_for(
                request,
                ("list-native", "footer-strip"),
                registry.t(lang_of(request), "home"),
                None,
                [s.title for s in stories[:12]],
                home_country,
            ),
        )

    @app.get("/analisis", response_class=HTMLResponse)
    def analyses(request: Request, session: SessionDep, page: PageQ = 1, tipo: str | None = None):
        kind = tipo if tipo in ("analisis", "opinion") else None
        pieces = queries.latest_pieces(session, kind=kind, limit=20, offset=(page - 1) * 20)
        ads = ads_for(
            request,
            ("list-native", "footer-strip"),
            registry.t(lang_of(request), "analysis"),
            None,
            [p.title for p in pieces] + [p.dek or "" for p in pieces],
            settings.default_country,
        )
        return render(request, "analyses.html", pieces=pieces, page=page, tipo=kind, ads=ads)

    @app.get("/tema/{ref}", response_class=HTMLResponse)
    def topic(request: Request, ref: str, session: SessionDep):
        tp, pieces, stories = queries.topic_view(session, ref_id(ref))
        if tp is None:
            raise HTTPException(404)
        title = pieces["analisis"].title if "analisis" in pieces else tp.title
        if redirect := canonical(request, "tema", tp.id, title):
            return redirect
        synth = (pieces["analisis"].synthesis or {}) if "analisis" in pieces else {}
        slugs = [m["medio_slug"] for m in synth.get("que_dice_cada_medio", [])]
        ids = [s.id for s in stories]
        outlets = queries.outlets_by_slug(session, slugs)
        verdicts = queries.verdict_counts(session, ids)
        return render(
            request,
            "topic.html",
            tp=tp,
            title=title,
            pieces=pieces,
            stories=stories,
            synth=synth,
            view=topicview.build(queries.topic_articles(session, tp.id), synth, outlets, verdicts),
            outlet_names=queries.story_outlet_names(session, ids),
            verdicts=verdicts,
        )

    @app.get("/verificaciones", response_class=HTMLResponse)
    def verifications(request: Request, session: SessionDep):
        return render(request, "verifications.html", claims=queries.all_verifications(session))

    @app.get("/historia/{ref}", response_class=HTMLResponse)
    def story(request: Request, ref: str, session: SessionDep, medio: str | None = None):
        st = session.get(Story, ref_id(ref))
        if st is None:
            raise HTTPException(404)
        if redirect := canonical(request, "historia", st.id, st.title):
            return redirect
        arts = queries.story_articles(session, st.id)
        related = [
            r
            for r in queries.top_stories(session, country=st.country, category=st.category, limit=7)
            if r.id != st.id
        ][:6]
        comp = compare(arts)
        claims = queries.claims_for_story(session, st.id)
        outlets_view = story_outlets(arts, comp, claims)
        if medio:  # llegada desde /noticia: la ficha de ese medio va primero y destacada
            outlets_view.sort(key=lambda o: o["outlet"].slug != medio)
        outside = abroad.for_story(session, st.id)
        return render(
            request,
            "story.html",
            target=medio,
            st=st,
            arts=arts,
            comp=comp,
            claims=claims,
            related=related,
            thread=queries.thread_for_story(session, st.id),
            outlets_view=outlets_view,
            share=social.share_links(
                settings.site_url + seo.path("historia", st.id, st.title), share_text(st, comp)
            ),
            spread=spread(arts),
            abroad=sorted(outside, key=lambda a: a.outlet.country),
            tr=translate.titles(session, [a.id for a in arts + outside], lang_of(request)),
            ads=ads_for(
                request,
                ("story-inline", "footer-strip"),
                st.title,
                st.category,
                [a.title for a in arts] + [a.summary or "" for a in arts],
                st.country,
            ),
        )

    @app.get("/hilo/{ref}", response_class=HTMLResponse)
    def thread(request: Request, ref: str, session: SessionDep):
        th = session.get(Thread, ref_id(ref))
        if th is None or th.status != "publicado":
            raise HTTPException(404)
        if redirect := canonical(request, "hilo", th.id, th.title):
            return redirect
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
            ads=list_ads(
                request, registry.category_name(slug, lang_of(request)), items, settings.default_country, slug
            ),
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
            ads=list_ads(request, registry.country_name(iso, lang_of(request)), items, iso),
        )

    @app.get("/region/{code}", response_class=HTMLResponse)
    def region(request: Request, code: str, session: SessionDep, page: PageQ = 1):
        code = code.upper()
        iso = code.split("-")[0]
        if code not in registry.countries().get(iso, {}).get("regions", {}):
            raise HTTPException(404)
        items = queries.latest(session, region=code, page=page)
        heading = registry.region_name(code)
        return render(
            request,
            "list.html",
            items=items,
            page=page,
            heading=heading,
            ads=list_ads(request, heading, items, iso),
        )

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
        profile = queries.outlet_profile(session, o.id)
        return render(
            request,
            "list.html",
            items=items,
            page=page,
            heading=o.name,
            outlet=o,
            record=record,
            profile=profile,
            ads=list_ads(request, o.name, items, o.country),
        )

    @app.get("/noticia/{ref}", response_class=HTMLResponse)
    def article(request: Request, ref: str, session: SessionDep):
        a = session.get(Article, ref_id(ref))
        if a is None:
            raise HTTPException(404)
        if redirect := canonical(request, "noticia", a.id, a.title):
            return redirect
        # Una noticia suelta aporta poco: si varios medios la cuentan, se va a la comparativa con su
        # medio primero y destacado (peticion del usuario 2026-10-19). La ficha de captura sigue en ?ficha=1.
        contrasted = a.story is not None and a.story.n_outlets >= 2
        if contrasted and "ficha" not in request.query_params:
            slug = a.outlet.slug
            return RedirectResponse(
                seo.path("historia", a.story_id, a.story.title) + f"?medio={slug}#m-{slug}", status_code=302
            )
        related = [
            s
            for s in queries.top_stories(
                session, country=a.country, category=a.category, hours=24 * 7, limit=7
            )
            if s.id != a.story_id
        ][:6]
        return render(
            request,
            "article.html",
            a=a,
            contrasted=contrasted,
            related=related,
            outlet_names=queries.story_outlet_names(session, [s.id for s in related]),
            verdicts=queries.verdict_counts(session, [s.id for s in related]),
            cites=citations.cited_figures(a),
            claims=queries.article_claims(session, a.id),
            archive_url=citations.archive_url(a),
        )

    @app.get("/publicidad", response_class=HTMLResponse)
    def advertising(request: Request):
        return render(request, "advertising.html")

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

    @app.get("/investigacion/{ref}", response_class=HTMLResponse)
    def investigation(request: Request, ref: str, session: SessionDep):
        inv = session.get(Investigation, ref_id(ref))
        if inv is None or inv.status != "publicada":
            raise HTTPException(404)
        if redirect := canonical(request, "investigacion", inv.id, investigation_title(inv)):
            return redirect
        return render(request, "investigation.html", inv=inv, r=inv.report)

    app.include_router(admin.make_router(settings, get_session, templates, render))

    return app
