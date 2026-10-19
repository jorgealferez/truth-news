"""Sitemaps para buscadores (ADR 0034): indice, ficheros de como mucho 1000 URLs y Google News.

`/sitemap.xml` es un indice. Cada tipo de pagina (paginas fijas y listados, historias, temas, hilos,
investigaciones, verificaciones) se reparte en ficheros `/sitemaps/<tipo>-<n>.xml` de `PAGE_SIZE` URLs
ordenadas por id: lo antiguo queda en los primeros ficheros y no cambia, y el buscador solo vuelve a
leer los que tienen un `lastmod` nuevo en el indice. Cada URL lleva `lastmod` con fecha y hora W3C (el
ultimo cambio real del contenido, nunca la hora de la peticion), `changefreq` segun la edad y `priority`
segun cuantos medios la cuentan y lo reciente que es. `/sitemaps/news.xml` sigue el formato de Google
News: lo publicado en las ultimas `NEWS_HOURS` horas, como mucho 1000 URLs, con titulo y fecha de
publicacion. Las versiones en otro idioma indexado viven bajo `/sitemaps/<idioma>/` con sus hreflang.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from xml.sax.saxutils import escape

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

from truthnews import registry
from truthnews.models import Claim, Investigation, Outlet, Story, Thread, Topic, Verification
from truthnews.web import queries, seo

PAGE_SIZE = 1000  # tope pedido por el usuario (el protocolo admite 50 000)
NEWS_HOURS = 48  # Google News solo lee lo publicado en los dos ultimos dias
NEWS_MAX = 1000  # tope del formato de Google News
MIN_OUTLETS = 2  # una historia de un solo medio no tiene contraste: no se ofrece al buscador

NS = (
    'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    ' xmlns:xhtml="http://www.w3.org/1999/xhtml"'
    ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"'
)
NS_NEWS = (
    'xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"'
    ' xmlns:news="http://www.google.com/schemas/sitemap-news/0.9"'
)

# Paginas fijas y listados: (ruta, changefreq, priority). Los listados cambian con cada ciclo del worker.
FIXED = (
    ("/", "hourly", 1.0),
    ("/contrastes", "hourly", 0.9),
    ("/verificaciones", "hourly", 0.9),
    ("/analisis", "hourly", 0.8),
    ("/discrepancias", "hourly", 0.8),
    ("/quien-dice-la-verdad", "daily", 0.8),
    ("/medios", "daily", 0.7),
    ("/investigaciones", "daily", 0.6),
    ("/nombramientos", "daily", 0.6),
    ("/presupuestos", "monthly", 0.4),
    ("/metodologia", "monthly", 0.4),
    ("/acerca", "yearly", 0.3),
    ("/publicidad", "yearly", 0.2),
)
LISTINGS = {"/", "/contrastes", "/verificaciones", "/analisis", "/discrepancias"}


@dataclass(frozen=True)
class Entry:
    path: str
    lastmod: datetime | None = None
    changefreq: str | None = None
    priority: float | None = None
    image: str | None = None  # ruta de la imagen de la pagina (sitemap de imagenes)


@dataclass(frozen=True)
class NewsEntry:
    path: str
    title: str
    published: datetime


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def w3c(value: datetime) -> str:
    """Fecha y hora W3C en UTC: '2026-10-19T08:05:00+00:00' (sin microsegundos)."""
    return _utc(value).replace(microsecond=0).isoformat()


def _latest(*values: datetime | None) -> datetime | None:
    present = [_utc(v) for v in values if v is not None]
    return max(present) if present else None


def changefreq(lastmod: datetime | None, now: datetime) -> str:
    """Lo vivo se revisa a menudo; lo que lleva semanas quieto, poco."""
    if lastmod is None:
        return "monthly"
    age = now - _utc(lastmod)
    if age < timedelta(days=1):
        return "hourly"
    if age < timedelta(days=7):
        return "daily"
    if age < timedelta(days=30):
        return "weekly"
    return "monthly"


def recency_bonus(lastmod: datetime | None, now: datetime) -> float:
    if lastmod is None:
        return 0.0
    age = now - _utc(lastmod)
    if age < timedelta(days=2):
        return 0.2
    if age < timedelta(days=7):
        return 0.1
    return 0.0


def _clamp(value: float) -> float:
    return round(min(max(value, 0.1), 1.0), 1)


def story_priority(n_outlets: int, lastmod: datetime | None, now: datetime) -> float:
    """0.5 de base, hasta +0.3 por medios que la cuentan (10 o mas) y hasta +0.2 si es reciente."""
    spread = min(max(n_outlets - 1, 0), 9) / 9 * 0.3
    return _clamp(0.5 + spread + recency_bonus(lastmod, now))


def _priority(base: float, lastmod: datetime | None, now: datetime) -> float:
    return _clamp(base + recency_bonus(lastmod, now))


# --- tipos de pagina ---------------------------------------------------------------------------
# Cada tipo da una consulta ordenada por id (paginacion estable) y como convertir una fila en Entry.


@dataclass(frozen=True)
class Kind:
    name: str
    query: Callable[[], Select]
    entry: Callable[[tuple, datetime, dict], Entry]
    dates: tuple  # columnas de fecha cuyo maximo es el lastmod (el indice solo lee estas)
    context: Callable[[Session], dict] = lambda _s: {}


def _story_entry(row, now, _ctx) -> Entry:
    sid, title, last_seen, updated, n_outlets = row
    mod = _latest(last_seen, updated)
    return Entry(
        seo.path("historia", sid, title),
        mod,
        changefreq(mod, now),
        story_priority(n_outlets or 0, mod, now),
        image=f"/og/historia/{sid}.png",
    )


def _topic_entry(row, now, ctx) -> Entry:
    tid, title, last_seen, updated = row
    mod = _latest(last_seen, updated)
    title = ctx["titles"].get(tid, title)
    return Entry(seo.path("tema", tid, title), mod, changefreq(mod, now), _priority(0.6, mod, now))


def _thread_entry(row, now, _ctx) -> Entry:
    hid, title, updated = row
    mod = _utc(updated)
    return Entry(seo.path("hilo", hid, title), mod, changefreq(mod, now), _priority(0.7, mod, now))


def _investigation_entry(row, now, _ctx) -> Entry:
    inv_id, question, report, updated = row
    mod = _utc(updated)
    title = (report or {}).get("analisis", {}).get("titular") or question
    return Entry(
        seo.path("investigacion", inv_id, title), mod, changefreq(mod, now), _priority(0.6, mod, now)
    )


def _verification_entry(row, now, _ctx) -> Entry:
    cid, checked = row
    mod = _utc(checked)
    return Entry(f"/verificacion/{cid}", mod, changefreq(mod, now), _priority(0.6, mod, now))


KINDS = {
    k.name: k
    for k in (
        Kind(
            "historias",
            lambda: (
                select(Story.id, Story.title, Story.last_seen, Story.updated_at, Story.n_outlets)
                .where(Story.n_outlets >= MIN_OUTLETS)
                .order_by(Story.id)
            ),
            _story_entry,
            (Story.last_seen, Story.updated_at),
        ),
        Kind(
            "temas",
            lambda: select(Topic.id, Topic.title, Topic.last_seen, Topic.updated_at).order_by(Topic.id),
            _topic_entry,
            (Topic.last_seen, Topic.updated_at),
            lambda s: {"titles": queries.topic_titles(s)},
        ),
        Kind(
            "hilos",
            lambda: (
                select(Thread.id, Thread.title, Thread.updated_at)
                .where(Thread.status == "publicado")
                .order_by(Thread.id)
            ),
            _thread_entry,
            (Thread.updated_at,),
        ),
        Kind(
            "investigaciones",
            lambda: (
                select(
                    Investigation.id, Investigation.question, Investigation.report, Investigation.updated_at
                )
                .where(Investigation.status == "publicada")
                .order_by(Investigation.id)
            ),
            _investigation_entry,
            (Investigation.updated_at,),
        ),
        Kind(
            # Las "sin datos" no se ofrecen: no aportan un veredicto que buscar.
            "verificaciones",
            lambda: (
                select(Claim.id, Verification.checked_at)
                .join(Verification, Verification.claim_id == Claim.id)
                .where(Verification.verdict != "sin-datos")
                .order_by(Claim.id)
            ),
            _verification_entry,
            (Verification.checked_at,),
        ),
    )
}
ORDER = ("paginas", *KINDS)


def page_entries(session: Session, now: datetime) -> list[Entry]:
    """Paginas fijas, listados, secciones, paises, comunidades y medios."""
    fresh = _utc(session.scalar(select(func.max(Story.last_seen)).where(Story.n_outlets >= MIN_OUTLETS)))
    out = [Entry(p, fresh if p in LISTINGS else None, cf, pr) for p, cf, pr in FIXED]
    out += [Entry(f"/seccion/{c}", None, "hourly", 0.7) for c in registry.categories()]
    for iso, country in registry.countries().items():
        out.append(Entry(f"/pais/{iso}", None, "hourly", 0.7))
        out += [Entry(f"/region/{code}", None, "daily", 0.5) for code in (country.get("regions") or {})]
    out += [
        Entry(f"/medio/{slug}", None, "daily", 0.5)
        for slug in session.scalars(select(Outlet.slug).order_by(Outlet.id))
    ]
    return out


def entries(session: Session, kind: str, now: datetime, page: int | None = None) -> list[Entry]:
    """Las URLs de un tipo; con `page` (desde 1), solo las de ese fichero."""
    if kind == "paginas":
        rows = page_entries(session, now)
        return rows if page is None else rows[(page - 1) * PAGE_SIZE : page * PAGE_SIZE]
    k = KINDS[kind]
    q = k.query()
    if page is not None:
        q = q.offset((page - 1) * PAGE_SIZE).limit(PAGE_SIZE)
    ctx = k.context(session)
    return [k.entry(tuple(r), now, ctx) for r in session.execute(q)]


def index_files(session: Session, now: datetime) -> list[tuple[str, datetime | None]]:
    """(nombre de fichero, lastmod) de cada fichero del indice; sin ficheros vacios."""
    files: list[tuple[str, datetime | None]] = []
    for kind in ORDER:
        if kind == "paginas":
            mods = [e.lastmod for e in page_entries(session, now)]
        else:  # solo las fechas, en el mismo orden que los ficheros: sin construir URLs
            k = KINDS[kind]
            q = k.query().with_only_columns(*k.dates, maintain_column_froms=True)
            mods = [_latest(*row) for row in session.execute(q)]
        for n, start in enumerate(range(0, len(mods), PAGE_SIZE), start=1):
            files.append((f"{kind}-{n}", _latest(*mods[start : start + PAGE_SIZE])))
    return files


def news_entries(session: Session, now: datetime) -> list[NewsEntry]:
    """Lo publicado en las ultimas NEWS_HOURS horas: historias contrastadas, hilos e investigaciones."""
    since = now - timedelta(hours=NEWS_HOURS)
    out = [
        NewsEntry(seo.path("historia", sid, title), title, _utc(first))
        for sid, title, first in session.execute(
            select(Story.id, Story.title, Story.first_seen)
            .where(Story.n_outlets >= MIN_OUTLETS, Story.first_seen >= since)
            .order_by(Story.first_seen.desc())
            .limit(NEWS_MAX)
        )
    ]
    out += [
        NewsEntry(seo.path("hilo", hid, title), title, _utc(created))
        for hid, title, created in session.execute(
            select(Thread.id, Thread.title, Thread.created_at).where(
                Thread.status == "publicado", Thread.created_at >= since
            )
        )
    ]
    for inv_id, question, report, created in session.execute(
        select(
            Investigation.id, Investigation.question, Investigation.report, Investigation.created_at
        ).where(Investigation.status == "publicada", Investigation.created_at >= since)
    ):
        title = (report or {}).get("analisis", {}).get("titular") or question
        out.append(NewsEntry(seo.path("investigacion", inv_id, title), title, _utc(created)))
    out.sort(key=lambda e: e.published, reverse=True)
    return out[:NEWS_MAX]


# --- XML ---------------------------------------------------------------------------------------


def _alternate_links(path: str, base: str, alternates: dict[str, str]) -> str:
    links = ""
    for lang, prefix in alternates.items():
        href = base + (prefix + ("" if path == "/" else path) if prefix else path)
        links += f'<xhtml:link rel="alternate" hreflang="{lang}" href="{escape(href)}"/>'
    return links + f'<xhtml:link rel="alternate" hreflang="x-default" href="{escape(base + path)}"/>'


def urlset_xml(
    rows: Iterable[Entry],
    base: str,
    localize: Callable[[str], str] = lambda p: p,
    alternates: dict[str, str] | None = None,
) -> str:
    """<urlset> con lastmod, changefreq, priority, imagen y, con `alternates`, los hreflang."""
    out = []
    for e in rows:
        parts = [f"<loc>{escape(base + localize(e.path))}</loc>"]
        if e.lastmod:
            parts.append(f"<lastmod>{w3c(e.lastmod)}</lastmod>")
        if e.changefreq:
            parts.append(f"<changefreq>{e.changefreq}</changefreq>")
        if e.priority is not None:
            parts.append(f"<priority>{e.priority:.1f}</priority>")
        if alternates:
            parts.append(_alternate_links(e.path, base, alternates))
        if e.image:
            parts.append(f"<image:image><image:loc>{escape(base + e.image)}</image:loc></image:image>")
        out.append("<url>" + "".join(parts) + "</url>")
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset {NS}>' + "".join(out) + "</urlset>\n"


def index_xml(files: Iterable[tuple[str, datetime | None]]) -> str:
    """<sitemapindex>: `files` son (URL absoluta, lastmod)."""
    rows = "".join(
        f"<sitemap><loc>{escape(loc)}</loc>"
        + (f"<lastmod>{w3c(mod)}</lastmod>" if mod else "")
        + "</sitemap>"
        for loc, mod in files
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">' + rows + "</sitemapindex>\n"
    )


def news_xml(rows: Iterable[NewsEntry], base: str, publication: str, language: str) -> str:
    """Sitemap de Google News: nombre del medio, idioma, fecha de publicacion y titulo por URL."""
    out = "".join(
        f"<url><loc>{escape(base + e.path)}</loc><news:news><news:publication>"
        f"<news:name>{escape(publication)}</news:name><news:language>{escape(language)}</news:language>"
        f"</news:publication><news:publication_date>{w3c(e.published)}</news:publication_date>"
        f"<news:title>{escape(e.title)}</news:title></news:news></url>"
        for e in rows
    )
    return f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset {NS_NEWS}>' + out + "</urlset>\n"
