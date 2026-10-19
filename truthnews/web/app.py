"""Aplicacion FastAPI: portada, secciones, paises, comunidades, medios y noticia."""
# Sin `from __future__ import annotations`: FastAPI resuelve los alias Annotated locales al definir.

import time
from datetime import UTC, date, datetime, timedelta
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
from truthnews.ai import statements, translate
from truthnews.analysis import (
    abroad,
    figure_changes,
    ranking,
    reliability,
    repeated,
    speakers,
    statement_checks,
    timeliness,
)
from truthnews.analysis.compare import QUALIFIER_LABEL, compare
from truthnews.analysis.plain import in_plain_words
from truthnews.config import Settings, get_settings
from truthnews.db import get_engine, session_factory
from truthnews.elections import calendar as el_calendar
from truthnews.elections import views as el_views
from truthnews.entities import views as entity_views
from truthnews.models import Article, ArticleRevision, Investigation, Outlet, Story, Thread
from truthnews.social import images, today
from truthnews.social import select as select_social
from truthnews.web import (
    admin,
    appointments,
    budget,
    charts,
    citations,
    contracts,
    council,
    legal,
    queries,
    seo,
    sitemaps,
    social,
    topicview,
)
from truthnews.web import structured as ld
from truthnews.web import verdicts as vview
from truthnews.web.langprefix import LangPrefix, localize

_dato = vview.dato  # nombre historico: lo usan plantillas y tests
HERE = Path(__file__).resolve().parent
RSS_DAYS = 14
RSS_MAX_ITEMS = 100


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


def _epoch_ms(value: datetime | None) -> int:
    """Marca de tiempo en ms para el JS de la portada (lo nuevo desde la ultima visita)."""
    if value is None:
        return 0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return int(value.timestamp() * 1000)


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
    boe_days: appointments.BoeDays | None = None,
    igae_extract: budget.LatestExtract | None = None,
    boe_index: appointments.BoeIndex | None = None,
    elections: el_calendar.Calendar | None = None,
    council_index: council.CouncilIndex | None = None,
    boe_contracts: contracts.BoeContractDays | None = None,
    ted_awards: contracts.TedAwards | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    ads_client = ads_client or adsmod.AdsClient(settings.ads_service_url, settings.ads_site_key)
    boe_days = boe_days or appointments.BoeDays()
    boe_index = boe_index or appointments.BoeIndex(boe_days, settings.boe_index_days)
    igae_extract = igae_extract or budget.LatestExtract()
    elections = elections or el_calendar.Calendar(settings.elections_lookback_days)
    council_index = council_index or council.CouncilIndex()
    boe_contracts = boe_contracts or contracts.BoeContractDays()
    ted_awards = ted_awards or contracts.TedAwards()
    cited_firms = contracts.CitedFirms(ted_awards)
    engine = engine or get_engine(settings.database_url)
    make_session = session_factory(engine)
    app = FastAPI(title=settings.site_name, docs_url="/api/docs", redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")
    # Paginas en otros idiomas bajo /<lang>/ (SEO: una URL indexable por idioma, con hreflang).
    prefixed = [lang for lang in registry.languages() if lang != settings.default_language]
    app.add_middleware(LangPrefix, prefixes=prefixed, site_url=settings.site_url)
    indexed = [lang for lang in registry.languages() if lang in settings.indexed_languages]
    indexed_prefixed = [lang for lang in prefixed if lang in indexed]
    templates = Jinja2Templates(directory=HERE / "templates")
    templates.env.filters["ago"] = _ago
    templates.env.filters["epoch_ms"] = _epoch_ms
    templates.env.filters["num"] = lambda v: f"{v:,.0f}".replace(",", ".")
    templates.env.filters["pct"] = lambda v, sign=False: (f"{v:+.1f}" if sign else f"{v:.1f}").replace(
        ".", ","
    )
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
        indexed_languages=indexed,
        lang_path=lambda path, lang: path if lang == settings.default_language else localize(path, lang),
        piece_url=seo.piece_path,
        investigation_title=investigation_title,
        verdict_line=vview.sentence,
        retired_note=vview.retired_note,
        # Seccion temporal (ADR 0036): solo hay enlace mientras alguna eleccion este en ventana.
        elections_nav=lambda: elections.active(),
        ld=ld,
        jsonld=ld.jsonld,
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

    view_cache: dict = {}

    def cached(key: tuple, seconds: float, build):
        # Vistas caras que solo cambian con el ciclo del worker (/hoy, prensa de /contratos): se
        # recalculan como mucho cada `seconds`; la primera visita tras caducar paga el calculo.
        now = time.monotonic()
        hit = view_cache.get(key)
        if hit is None or now - hit[0] > seconds:
            if len(view_cache) > 200:
                view_cache.clear()
            hit = view_cache[key] = (now, build())
        return hit[1]

    nocuadra_cache: dict = {}

    def nocuadra_cached(session: Session) -> list:
        # Lo que no cuadra en portada (ADR 0027): una sola consulta y 5 min de cache (cambia con el ciclo
        # del worker). Solo falsedades con dato oficial y al menos 2; con menos, el bloque no sale.
        now = time.monotonic()
        if not nocuadra_cache or now - nocuadra_cache["at"] > 300:
            found = [f for f in ranking.falsehoods(session, limit=10) if f.official is not None][:3]
            nocuadra_cache.update(at=now, value=found if len(found) >= 2 else [])
        return nocuadra_cache["value"]

    def lang_of(request: Request) -> str:
        prefix = getattr(request.state, "lang_prefix", None)
        if prefix:
            return prefix
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

    def story_translations(ctx: dict, lang: str) -> dict[int, str]:
        """Titulares traducidos de las historias que pinta la pagina (portada, listas, la propia historia)."""
        ids = set()
        for v in ctx.values():
            for x in v if isinstance(v, list) else [v]:
                if isinstance(x, Story):
                    ids.add(x.id)
        if not ids:
            return {}
        session = make_session()
        try:
            return queries.story_title_translations(session, sorted(ids), lang)
        finally:
            session.close()

    def render(request: Request, name: str, **ctx) -> HTMLResponse:
        lang = lang_of(request)
        ctx.setdefault("st_tr", story_translations(ctx, lang) if lang != settings.default_language else {})
        resp = templates.TemplateResponse(request, name, {"lang": lang, "ads": {}, **ctx})
        if request.query_params.get("lang") == lang:
            resp.set_cookie("lang", lang, max_age=60 * 60 * 24 * 365, samesite="lax")
        return resp

    def ads_for(request: Request, slots, title: str, category, texts, country: str) -> dict:
        """Anuncios por el contenido de la pagina (ads-service); {} si no hay servicio o falla."""
        if not ads_client.enabled or adsmod.sensitive([title, *texts]):
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
            "User-agent: *\nDisallow: /admin\nDisallow: /api/\n"
            + "".join(
                f"Sitemap: {settings.site_url}/sitemap{s}.xml\n"
                for s in ["", *(f"-{p}" for p in indexed_prefixed)]
            )
            + f"Sitemap: {settings.site_url}/sitemaps/news.xml\n"
        )

    def sitemap_response(body: str, lastmod: datetime | None, max_age: int) -> Response:
        # Los sitemaps no son resultados de busqueda; la cache corta evita rehacer la consulta a cada robot.
        headers = {"Cache-Control": f"public, max-age={max_age}", "X-Robots-Tag": "noindex"}
        if lastmod:
            headers["Last-Modified"] = lastmod.astimezone(UTC).strftime("%a, %d %b %Y %H:%M:%S GMT")
        return Response(body, media_type="application/xml", headers=headers)

    def sitemap_index(session: Session, lang: str | None) -> Response:
        now = datetime.now(UTC)
        folder = f"{settings.site_url}/sitemaps/" + (f"{lang}/" if lang else "")
        files = [(f"{folder}{name}.xml", mod) for name, mod in sitemaps.index_files(session, now)]
        if not lang:  # Google News: solo el idioma por omision, que es el del contenido
            news = sitemaps.news_entries(session, now)
            files.insert(0, (f"{folder}news.xml", news[0].published if news else None))
        mods = [m for _, m in files if m]
        return sitemap_response(sitemaps.index_xml(files), max(mods) if mods else None, 300)

    def sitemap_file(session: Session, name: str, lang: str | None) -> Response:
        now = datetime.now(UTC)
        kind, _, n = name.rpartition("-")
        if kind not in sitemaps.ORDER or not n.isdigit() or int(n) < 1:
            raise HTTPException(404)
        rows = sitemaps.entries(session, kind, now, page=int(n))
        if not rows:
            raise HTTPException(404)
        alternates = {settings.default_language: "", **{p: f"/{p}" for p in indexed_prefixed}}
        body = sitemaps.urlset_xml(
            rows,
            settings.site_url,
            localize=(lambda path: localize(path, lang)) if lang else (lambda path: path),
            alternates=alternates if len(alternates) > 1 else None,
        )
        mods = [e.lastmod for e in rows if e.lastmod]
        return sitemap_response(body, max(mods) if mods else None, 900)

    @app.get("/sitemap.xml", include_in_schema=False)
    def sitemap(session: SessionDep):
        return sitemap_index(session, None)

    @app.get("/sitemap-{lang}.xml", include_in_schema=False)
    def sitemap_lang(lang: str, session: SessionDep):
        if lang not in indexed_prefixed:
            raise HTTPException(404)
        return sitemap_index(session, lang)

    @app.get("/sitemaps/news.xml", include_in_schema=False)
    def sitemap_news(session: SessionDep):
        rows = sitemaps.news_entries(session, datetime.now(UTC))
        body = sitemaps.news_xml(rows, settings.site_url, settings.site_name, settings.default_language)
        return sitemap_response(body, rows[0].published if rows else None, 300)

    @app.get("/sitemaps/{name}.xml", include_in_schema=False)
    def sitemap_part(name: str, session: SessionDep):
        return sitemap_file(session, name, None)

    @app.get("/sitemaps/{lang}/{name}.xml", include_in_schema=False)
    def sitemap_part_lang(lang: str, name: str, session: SessionDep):
        if lang not in indexed_prefixed:
            raise HTTPException(404)
        return sitemap_file(session, name, lang)

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
                "link": settings.site_url + seo.piece_path(p),
                "description": p.dek or "",
                "date": p.created_at if p.created_at.tzinfo else p.created_at.replace(tzinfo=UTC),
            }
            for p in queries.latest_pieces(session, limit=20)
        ]
        # Hilos publicados y verificaciones con fuente, con las mismas reglas que las redes (ADR 0018).
        since = datetime.now(UTC) - timedelta(days=RSS_DAYS)
        lang = settings.default_language
        for c in select_social.threads(session, settings.site_url, since, lang) + select_social.verifications(
            session, settings.site_url, since, lang
        ):
            items.append(
                {
                    "title": c.draft.headline,
                    "link": c.draft.url,
                    "description": " ".join(ln for ln in c.draft.lines if ln),
                    "date": c.date if c.date.tzinfo else c.date.replace(tzinfo=UTC),
                }
            )
        items.sort(key=lambda i: i["date"], reverse=True)
        items = items[:RSS_MAX_ITEMS]
        xml = social.rss_xml(
            settings.site_name, settings.site_url, registry.t(settings.default_language, "tagline"), items
        )
        return Response(xml, media_type="application/rss+xml")

    image_cache: dict[tuple, bytes] = {}

    def today_view(session: Session, lang: str) -> tuple[list, str]:
        now = datetime.now(UTC)
        items = cached(("hoy", lang, now.date()), 300, lambda: today.keys(session, now, lang))
        return items, now.strftime("%d/%m/%Y")

    @app.get("/hoy", response_class=HTMLResponse)
    def today_page(request: Request, session: SessionDep):
        # Hoy en 1 minuto (ADR 0047): las claves del dia, solo con lo contrastado; si no hay, se dice.
        lang = lang_of(request)
        items, date_label = today_view(session, lang)
        url = f"{settings.site_url}/hoy"
        return render(
            request,
            "today.html",
            items=items,
            date_label=date_label,
            share=social.share_links(url, f"{registry.t(lang, 'today_title')} — {date_label}"),
        )

    @app.get("/hoy.xml", include_in_schema=False)
    def today_rss(session: SessionDep):
        lang = settings.default_language
        items, _ = today_view(session, lang)
        rows = [
            {
                "title": k.sentence,
                "link": settings.site_url + k.path,
                "description": " · ".join(
                    x
                    for x in (
                        registry.t(lang, "verdict_" + k.verdict) if k.verdict else None,
                        k.official and f"{registry.t(lang, 'today_official')}: {k.official} ({k.period})",
                        f"{registry.t(lang, 'today_source')}: {k.source}",
                    )
                    if x
                ),
                "date": k.when if k.when.tzinfo else k.when.replace(tzinfo=UTC),
            }
            for k in items
        ]
        title = f"{settings.site_name} — {registry.t(lang, 'today_title')}"
        xml = social.rss_xml(title, f"{settings.site_url}/hoy", registry.t(lang, "today_lead"), rows)
        return Response(xml, media_type="application/rss+xml")

    @app.get("/og/hoy-{fmt}.png", include_in_schema=False)
    def today_og(fmt: str, session: SessionDep):
        if fmt not in social.TODAY_SIZES:
            raise HTTPException(404)
        lang = settings.default_language
        items, date_label = today_view(session, lang)
        key = ("hoy", fmt, date_label, tuple((k.kind, k.ref_id) for k in items))
        if key not in image_cache:
            if len(image_cache) > 500:
                image_cache.clear()
            image_cache[key] = social.today_image(
                [
                    (
                        k.verdict,
                        registry.t(lang, "verdict_" + k.verdict)
                        if k.verdict
                        else registry.t(lang, "today_dispute"),
                        k.sentence,
                    )
                    for k in items
                ],
                registry.t(lang, "today_title"),
                date_label,
                f"{settings.site_domain}/hoy",
                registry.t(lang, "today_empty"),
                fmt,
            )
        return Response(
            image_cache[key], media_type="image/png", headers={"Cache-Control": "public, max-age=900"}
        )

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

    @app.get("/ahora.json")
    def now_json(session: SessionDep):
        # Lo que consulta la portada abierta cada pocos minutos para avisar, sin recargar, de que hay
        # novedades: la ultima historia en movimiento y el ultimo rastreo (carril de ultimo minuto).
        items = queries.breaking(session, settings.default_country, limit=1)
        last = totals_cached(session)["last_crawl"]
        return JSONResponse(
            {
                "latest": _epoch_ms(items[0]["story"].last_seen) if items else 0,
                "last_crawl": _epoch_ms(last),
            },
            headers={"Cache-Control": "public, max-age=60"},
        )

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
            breaking=queries.breaking(session, home_country),
            breaking_every=settings.breaking_interval_minutes or settings.crawl_interval_minutes,
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
            top_outlets=reliability.ranking(reliability.records(session, home_country))[0][:5],
            nocuadra=nocuadra_cached(session),
            min_checks=reliability.MIN_CHECKS,
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
            threads=queries.front_threads(session, ids),
        )

    @app.get("/verificacion/{claim_id}", response_class=HTMLResponse)
    def verification(request: Request, claim_id: int, session: SessionDep):
        c = queries.claim_detail(session, claim_id)
        if c is None or c.verification is None:
            raise HTTPException(404)
        lang = lang_of(request)
        line = vview.sentence(c, lang)
        url = f"{settings.site_url}/verificacion/{c.id}"
        # Enlazado interno (ADR 0038): la historia con su titular y quien aparece, hablante primero.
        story = session.get(Story, c.story_id) if c.story_id else None
        people = [(c.speaker, 1)] if c.speaker else []
        if c.story_id:
            found = entity_views.for_story(session, c.story_id, limit=4)
            people += [(e, n) for e, n in found if e != c.speaker]
        return render(
            request,
            "verification.html",
            c=c,
            v=c.verification,
            story=story,
            people=people[:4],
            line=line,
            chart=vview.chart(c, lang),
            series=vview.series_of(c),
            share=social.share_links(url, line),
            share_url=url,
        )

    @app.get("/verificaciones", response_class=HTMLResponse)
    def verifications(request: Request, session: SessionDep):
        return render(request, "verifications.html", claims=queries.all_verifications(session))

    @app.get("/repetidas", response_class=HTMLResponse)
    def repeated_claims(request: Request, session: SessionDep):
        return render(request, "repeated.html", groups=repeated.repeated(session))

    @app.get("/discrepancias", response_class=HTMLResponse)
    def discrepancies(request: Request, session: SessionDep):
        # Lo que no cuadra (ADR 0027): la noticia grande es donde los datos y lo publicado no coinciden.
        return render(
            request,
            "discrepancies.html",
            falsehoods=ranking.falsehoods(session, limit=20),
            discrepancies=ranking.discrepancies(session, country=settings.default_country, limit=12),
            contradictions=ranking.contradictions(session, limit=12),
            board=ranking.scoreboard(session),
        )

    @app.get("/quien-dice-la-verdad", response_class=HTMLResponse)
    def speakers_page(request: Request, session: SessionDep):
        recs = speakers.records(session)
        by_kind = {k: speakers.ranking([r for r in recs if r.entity.kind == k]) for k in speakers.KINDS}
        return render(
            request,
            "speakers.html",
            by_kind=by_kind,
            min_checks=reliability.MIN_CHECKS,
            no_channel=statement_checks.without_channel(country=settings.default_country),
        )

    @app.get("/entidades", response_class=HTMLResponse)
    def entities(request: Request, session: SessionDep, tipo: str | None = None, dias: int = 30):
        kind = tipo if tipo in ("persona", "partido", "institucion", "organizacion", "lugar") else None
        days = dias if dias in (7, 30, 365) else 30
        return render(
            request, "entities.html", rows=entity_views.ranking(session, kind, days), tipo=kind, dias=days
        )

    @app.get("/entidad/{ref}", response_class=HTMLResponse)
    def entity(request: Request, ref: str, session: SessionDep):
        p = entity_views.profile(session, ref_id(ref))
        if p is None:
            raise HTTPException(404)
        if redirect := canonical(request, "entidad", p.entity.id, p.entity.name):
            return redirect
        lang = lang_of(request)
        lanes = {k: registry.t(lang, f"chart_lane_{k}") for k in charts.LANE_KEYS}
        said = charts.said_timeline(
            charts.said_points(p.claims, p.quotes), lanes, registry.t(lang, "chart_said_title")
        )
        return render(request, "entity.html", p=p, e=p.entity, said=said)

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
        parties = statements.for_story(session, st)
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
            figure_charts=charts.story_figure_charts(
                arts,
                comp,
                claims,
                {k: registry.t(lang_of(request), f"chart_{k}") for k in ("official", "by_outlet", "changed")},
                revisions=list(
                    session.scalars(
                        select(ArticleRevision).where(ArticleRevision.article_id.in_([a.id for a in arts]))
                    )
                ),
            ),
            related=related,
            thread=queries.thread_for_story(session, st.id),
            outlets_view=outlets_view,
            plain=in_plain_words(comp, claims),
            missing=reliability.missing_outlets(session, st),
            fig_changes=figure_changes.for_story(session, st.id),
            repeats=repeated.repeated_for_story(session, st.id),
            timing=next(iter(timeliness.load(session, st.id)), None),
            share=social.share_links(
                settings.site_url + seo.path("historia", st.id, st.title), share_text(st, comp)
            ),
            spread=spread(arts),
            abroad=sorted(outside, key=lambda a: a.outlet.country),
            parties=parties,
            people=entity_views.for_story(session, st.id),
            tr=translate.titles(session, [a.id for a in arts + outside], lang_of(request)),
            boe=boe_index.confirmations(
                [st.title] + [f"{a.title} {a.summary or ''}" for a in arts], datetime.now(UTC).date()
            ),
            contracts_cited=cited_firms.in_texts(
                [st.title] + [f"{a.title} {a.summary or ''}" for a in arts], datetime.now(UTC).date()
            ),
            # Nunca junto a un veredicto ni a "Que dicen los partidos": ahi solo la franja del pie.
            ads=ads_for(
                request,
                ("footer-strip",) if claims or parties else ("story-inline", "footer-strip"),
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
        return render(
            request,
            "thread.html",
            th=th,
            c=th.content,
            sources=sources,
            piece=queries.thread_piece(session, th.id),
            topic=th.anchor.topic if th.anchor else None,
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
        country = pais.upper() if pais else None
        ranked, few = reliability.ranking(reliability.records(session, country))
        return render(
            request,
            "outlets.html",
            rows=queries.outlets(session, country),
            ranked=ranked,
            few=few,
            fig_records=figure_changes.by_outlet(session),
            timely=timeliness.by_outlet(timeliness.load(session)),
            min_stories=timeliness.MIN_STORIES,
            min_checks=reliability.MIN_CHECKS,
        )

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
            rel=next(iter(reliability.records(session, outlet_id=o.id)), None),
            checks=reliability.history(session, o.id),
            blind=reliability.blind_spots(session, o),
            fig_changes=figure_changes.for_outlet(session, o.id),
            min_checks=reliability.MIN_CHECKS,
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
            live=citations.is_live(a.title, *(x for r in a.revisions for x in (r.before, r.after))),
            boe=boe_index.confirmations([a.title, a.summary or ""], datetime.now(UTC).date()),
            contracts_cited=cited_firms.in_texts([a.title, a.summary or ""], datetime.now(UTC).date()),
        )

    @app.get("/consejo-de-ministros", response_class=HTMLResponse)
    def council_page(request: Request):
        today = datetime.now(UTC).date()
        return render(
            request,
            "council.html",
            councils=council_index.councils(today),
            today=today,
            publish_days=council.consejo.PUBLISH_DAYS,
        )

    @app.get("/nombramientos", response_class=HTMLResponse)
    def appointments_page(request: Request, session: SessionDep, fecha: str | None = None):
        today = datetime.now(UTC).date()
        if fecha:
            try:
                day = date.fromisoformat(fecha)
            except ValueError:
                raise HTTPException(404) from None
            if day > today or day < date(2009, 1, 1):  # la API de datos abiertos empieza en 2009
                raise HTTPException(404)
            items = boe_days.day(day, today)
        else:
            day, items = boe_days.latest(today)
        return render(
            request,
            "appointments.html",
            day=day,
            v=appointments.view(items),
            press=appointments.mentions(
                session,
                [i.persona for i in items if i.tipo in ("nombramiento", "cese") and i.persona],
                datetime.combine(day, datetime.min.time(), UTC) + timedelta(days=1),
            ),
            prev_day=day - timedelta(days=1),
            next_day=day + timedelta(days=1) if day < today else None,
        )

    @app.get("/contratos", response_class=HTMLResponse)
    def contracts_page(request: Request, session: SessionDep, fecha: str | None = None):
        today = datetime.now(UTC).date()
        if fecha:
            try:
                day = date.fromisoformat(fecha)
            except ValueError:
                raise HTTPException(404) from None
            if day > today or day < date(2009, 1, 1):  # la API de datos abiertos empieza en 2009
                raise HTTPException(404)
            items = boe_contracts.day(day, today)
        else:
            day, items = boe_contracts.latest(today)
        got = ted_awards.get(today)
        ted = contracts.ted_view(got[2]) if got else None
        return render(
            request,
            "contracts.html",
            day=day,
            boe=contracts.boe_view(items),
            ted=ted,
            ted_since=got[0] if got else None,
            ted_until=got[1] if got else None,
            press=cached(
                ("prensa", tuple(f["nombre"] for f in ted["firms"]) if ted else (), today),
                600,
                lambda: contracts.mentions(
                    session,
                    [f["nombre"] for f in ted["firms"]] if ted else [],
                    datetime.combine(today, datetime.min.time(), UTC) + timedelta(days=1),
                ),
            ),
            dep_name=appointments.dept_name,
            prev_day=day - timedelta(days=1),
            next_day=day + timedelta(days=1) if day < today else None,
        )

    @app.get("/presupuestos", response_class=HTMLResponse)
    def budget_page(request: Request):
        ex = igae_extract.get()
        return render(request, "budget.html", ex=ex, v=budget.view(ex) if ex else None)

    @app.get("/elecciones", response_class=HTMLResponse)
    def elections_page(request: Request, session: SessionDep):
        now = datetime.now(UTC)
        active = sorted(elections.active(session, now), key=lambda e: (e.country != "ES", e.date))
        return render(request, "elections.html", active=active, today=now.date())

    @app.get("/elecciones/{slug}", response_class=HTMLResponse)
    def election_page(request: Request, slug: str, session: SessionDep):
        now = datetime.now(UTC)
        e = elections.get(slug, session, now)
        if e is None:
            raise HTTPException(404)
        # Sin publicidad en paginas de elecciones (ads.py): ni se llama al servicio.
        return render(
            request, "election.html", v=el_views.page(session, e, now, elections.candidacies(e))
        )

    @app.get("/elecciones/{slug}/promesas", response_class=HTMLResponse)
    def election_promises(
        request: Request,
        slug: str,
        session: SessionDep,
        partido: str | None = None,
        tema: str | None = None,
        anio: Annotated[int | None, Query(ge=1977, le=2100)] = None,
    ):
        now = datetime.now(UTC)
        e = elections.get(slug, session, now)
        if e is None:
            raise HTTPException(404)
        actors = [a for a in registry.load_political() if a.country == e.country]
        actor = next((a for a in actors if a.slug == partido), None)
        if partido and actor is None:
            raise HTTPException(404)
        return render(
            request,
            "promises.html",
            e=e,
            actor=actor,
            actors=actors,
            topic=tema,
            names={a.slug: a.name for a in actors},
            v=el_views.promises_page(session, e, partido, tema, anio),
            cmp=el_views.compare_programs(session, e, partido) if partido else None,
        )

    @app.get("/publicidad", response_class=HTMLResponse)
    def advertising(request: Request):
        return render(request, "advertising.html")

    @app.get("/acerca", response_class=HTMLResponse)
    def about(request: Request):
        return render(request, "about.html")

    def legal_page(slug: str):
        def page(request: Request):
            return render(
                request,
                "legal.html",
                slug=slug,
                body=f"legal/{slug}.{legal.content_lang(lang_of(request))}.html",
                storage=legal.STORAGE,
                missing=legal.missing_owner_data(settings),
            )

        return page

    for slug in legal.PAGES:
        app.add_api_route(f"/{slug}", legal_page(slug), response_class=HTMLResponse, methods=["GET"])

    @app.get("/idioma/{lang}")
    def set_lang(lang: str, request: Request, to: str | None = None):
        safe = to if to and to.startswith("/") and not to.startswith("//") else None
        target = safe or request.headers.get("referer") or "/"
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

    # Retirar o restituir un veredicto vacia las vistas en cache: /hoy no lo sigue mostrando.
    app.include_router(
        admin.make_router(settings, get_session, templates, render, on_change=view_cache.clear)
    )

    return app
