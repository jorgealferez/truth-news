"""Importacion de noticias antiguas del archivo (ADR 0028, fuente segun ADR 0030).

Fuente: los ficheros GKG de GDELT (un fichero cada 15 minutos desde febrero de 2015, estaticos y sin
limite de peticiones). Cada fila es una noticia de la prensa mundial con su URL, medio, fecha y titular
original; el fichero "translation" trae la prensa en otras lenguas (castellano, catalan, portugues...).
La API DOC de GDELT responde 429 sin pausa desde IP compartidas (medido el 2026-10-19 desde Railway y
desde el contenedor), por eso no se usa aqui.

Se avanza hacia atras un tramo de 15 minutos cada `stride`, desde la noticia de archivo mas antigua que
ya tengamos, y se guardan solo las de medios del registro de los paises elegidos, marcadas con
`origin = 'archivo'`: titular, fecha y enlace; no se descarga la pagina del medio, igual que el rastreo
cita sin republicar (ADR 0003). Lo importado no se verifica contra el dato de hoy (seria juzgar 2019 con
2026): alimenta las fichas de entidad, la linea temporal y los hilos.
"""

from __future__ import annotations

import csv
import html
import io
import logging
import re
import time
import zipfile
from collections.abc import Callable, Iterable, Iterator
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from truthnews.classify import classify, topics
from truthnews.crawler.extract import canonical_url, sha256
from truthnews.data import client
from truthnews.models import Article, Outlet, utcnow

log = logging.getLogger(__name__)
BASE = "https://data.gdeltproject.org/gdeltv2"
FLOOR = datetime(2015, 2, 19, tzinfo=UTC)  # primer fichero GKG 2.0
SLOT = timedelta(minutes=15)
_TITLE = re.compile(r"<PAGE_TITLE>(.*?)</PAGE_TITLE>", re.S)
_SRC_LANG = re.compile(r"srclc:([a-z]{3})")
_LANG = {
    "spa": "es",
    "cat": "ca",
    "por": "pt",
    "fra": "fr",
    "deu": "de",
    "ita": "it",
    "glg": "gl",
    "eus": "eu",
}
# Columnas del GKG 2.1: 1 fecha, 2 coleccion (1 = web), 3 medio, 4 URL, 25 traduccion, 26 extras.
_DATE, _COLLECTION, _SOURCE, _URL, _TRANSLATION, _EXTRAS = 1, 2, 3, 4, 25, 26
csv.field_size_limit(10**8)


def _aware(dt: datetime) -> datetime:
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def host(url: str) -> str:
    h = urlsplit(url if "//" in url else f"//{url}").netloc.lower()
    return h[4:] if h.startswith("www.") else h


def floor_slot(dt: datetime) -> datetime:
    dt = _aware(dt)
    return dt.replace(minute=dt.minute - dt.minute % 15, second=0, microsecond=0)


def outlet_hosts(session: Session, countries: Iterable[str] | None = None) -> dict[str, Outlet]:
    q = select(Outlet).where(Outlet.active.is_(True))
    if countries:
        q = q.where(Outlet.country.in_(list(countries)))
    return {host(o.homepage): o for o in session.scalars(q)}


def file_urls(slot: datetime, hosts: dict[str, Outlet]) -> list[str]:
    """El fichero "translation" siempre; el ingles solo si algun medio elegido publica en ingles."""
    stamp = f"{slot:%Y%m%d%H%M%S}"
    urls = [f"{BASE}/{stamp}.translation.gkg.csv.zip"]
    if any(o.language == "en" for o in hosts.values()):
        urls.append(f"{BASE}/{stamp}.gkg.csv.zip")
    return urls


def download(url: str) -> bytes | None:
    """El zip del tramo, o None si ese tramo no existe (GDELT tiene huecos). Otros fallos se lanzan."""
    with client() as c:
        resp = c.get(url, follow_redirects=True, timeout=60)
    if resp.status_code == 404:
        return None
    resp.raise_for_status()
    return resp.content


def rows(payload: bytes) -> Iterator[list[str]]:
    with zipfile.ZipFile(io.BytesIO(payload)) as z:
        for name in z.namelist():
            with z.open(name) as f:
                text = io.TextIOWrapper(f, encoding="utf-8", errors="replace")
                yield from csv.reader(text, delimiter="\t", quoting=csv.QUOTE_NONE)


def parse(row: list[str], hosts: dict[str, Outlet]) -> dict | None:
    """Una fila del GKG como noticia de un medio del registro, o None si no lo es o no tiene titular."""
    if len(row) <= _EXTRAS or row[_COLLECTION] != "1":
        return None
    outlet = hosts.get(host(row[_SOURCE]))
    title = _TITLE.search(row[_EXTRAS])
    if outlet is None or title is None or not row[_URL].startswith("http"):
        return None
    clean = " ".join(html.unescape(title.group(1)).split())[:600]
    if not clean:
        return None
    try:
        when = datetime.strptime(row[_DATE], "%Y%m%d%H%M%S").replace(tzinfo=UTC)
    except ValueError:
        return None
    lang = _SRC_LANG.search(row[_TRANSLATION])
    return {
        "outlet": outlet,
        "url": canonical_url(row[_URL]),
        "title": clean,
        "date": when,
        "language": _LANG.get(lang.group(1), outlet.language) if lang else outlet.language,
    }


def oldest(session: Session, now: datetime) -> datetime:
    """Desde donde seguir: la noticia de archivo mas antigua, o la primera rastreada si aun no hay."""
    first = session.scalar(select(func.min(Article.published_at)).where(Article.origin == "archivo"))
    if first is None:
        first = session.scalar(select(func.min(Article.published_at)).where(Article.origin == "rss"))
    return floor_slot(min(_aware(first), now) if first else now)


def import_slot(
    session: Session,
    slot: datetime,
    hosts: dict[str, Outlet],
    now: datetime,
    fetch: Callable[[str], bytes | None] = download,
) -> dict:
    found = []
    for url in file_urls(slot, hosts):
        payload = fetch(url)
        if payload:
            found += [n for r in rows(payload) if (n := parse(r, hosts))]
    by_hash = {sha256(n["url"]): n for n in found}
    known = set()
    hashes = list(by_hash)
    for i in range(0, len(hashes), 500):
        chunk = hashes[i : i + 500]
        known |= set(session.scalars(select(Article.url_hash).where(Article.url_hash.in_(chunk))))
    new = 0
    for h, n in by_hash.items():
        if h in known:
            continue
        o = n["outlet"]
        session.add(
            Article(
                outlet_id=o.id,
                url=n["url"],
                url_hash=h,
                title=n["title"],
                published_at=min(n["date"], now),
                language=n["language"],
                country=o.country,
                region=o.region,
                category=classify(n["title"], "", n["url"], None, n["language"]),
                topics=topics(n["title"], None),
                origin="archivo",
            )
        )
        new += 1
    session.flush()
    return {"slot": f"{slot:%Y-%m-%d %H:%M}", "found": len(found), "new": new}


def run(
    session: Session,
    slots: int = 2,
    stride: timedelta = timedelta(hours=6),
    countries: Iterable[str] | None = ("ES",),
    now: datetime | None = None,
    fetch: Callable[[str], bytes | None] = download,
    clock: Callable[[], float] = time.monotonic,
    max_seconds: float = 120.0,
) -> dict:
    """Hasta `slots` tramos hacia atras, uno cada `stride`, sin pasar de `max_seconds`."""
    now = now or utcnow()
    hosts = outlet_hosts(session, countries)
    began = clock()
    done = []
    slot = oldest(session, now) - stride
    while len(done) < slots and slot >= FLOOR and hosts:
        if clock() - began > max_seconds:
            break
        try:
            with session.begin_nested():  # un tramo fallido no deshace los anteriores
                done.append(import_slot(session, slot, hosts, now, fetch))
        except Exception as exc:  # red o fichero roto: se reintenta en el ciclo siguiente
            log.warning("archivo: tramo %s fallo: %s", f"{slot:%Y-%m-%d %H:%M}", exc)
            break
        slot -= stride
    out = {"slots": len(done), "new": sum(d["new"] for d in done), "detail": done}
    log.info("archivo: %s tramos, %s noticias nuevas", out["slots"], out["new"])
    return out
