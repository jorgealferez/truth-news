"""Programas electorales y promesas (ADR 0037): se descubren en la web de cada partido y se citan.

1. Descubrir: la portada del partido (y las paginas de programas que enlaza o que da el registro) con el
   cliente educado del rastreador (User-Agent propio, robots.txt, ritmo por dominio). Un PDF es un
   programa si su enlace o su texto lo dicen y llevan el tipo de eleccion y el ano.
2. Importar: el PDF se descarga solo si robots.txt lo permite; se guarda su huella, sus paginas y el texto
   para analizarlo. Lo que se publica es la cita con su pagina y el enlace (ADR 0003).
3. Promesas: frases con un verbo de compromiso en futuro de primera persona del plural ("bajaremos",
   "vamos a", "nos comprometemos a"), citadas literalmente con su pagina y su tema. Tambien de las
   declaraciones de los canales oficiales durante la ventana de una eleccion.

Mismo metodo y mismo orden para todos los partidos. Un partido cuya web bloquea al rastreador queda
"no localizado" con el motivo; no se elude ningun bloqueo.
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import logging
import re
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from urllib.parse import urljoin, urlsplit

from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews import registry
from truthnews.classify import normalize
from truthnews.config import Settings
from truthnews.crawler.http import PoliteClient
from truthnews.models import PoliticalStatement, Program, Promise
from truthnews.registry import ActorSpec, load_political

log = logging.getLogger(__name__)

MAX_PDF_BYTES = 40 * 1024 * 1024
MAX_PAGES = 600
MAX_PROMISES = 1000
MAX_PAGES_TO_VISIT = 6
IMPORTS_PER_RUN = 3
DISCOVER_EVERY = timedelta(hours=6)
_LINK = re.compile(r"<a\b[^>]*?href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a>", re.S | re.I)
_TAGS = re.compile(r"<[^>]+>")
_PROGRAM_WORD = re.compile(r"\b(programa|programas|programes|programme|egitaraua|manifiesto|manifest)\b")
_YEAR = re.compile(r"(?<!\d)(19[89]\d|20\d\d)(?!\d)")
# Atajos de fecha electoral en los nombres de fichero: 23j = 23 de julio de 2023, 28m = 28 de mayo de 2023.
_SHORT = {"23j": ("generales", 2023), "23-j": ("generales", 2023), "28m": ("locales", 2023)}
_KIND_WORDS = (
    ("generales", re.compile(r"general|xerais|generals|orokor|congreso|congres")),
    ("europeas", re.compile(r"europe")),
    ("locales", re.compile(r"municip|locales|local|insular|cabildo|concello|ajuntament")),
    ("autonomicas", re.compile(r"autonom|galegas|parlament|catalanes|vascas|andaluzas|forales")),
)
# Futuro de 1.a del plural (es y gl: -remos; ca: -rem) y perifrasis de compromiso. "queremos" y
# "podemos" no son compromisos (presente).
_COMMIT = re.compile(
    r"\b(vamos a|imos|nos comprometemos|comprometemonos|ens comprometem|"
    r"[a-z]{2,}(?:aremos|eremos|iremos)|[a-z]{3,}(?:arem|erem|irem))\b"
)
_NOT_COMMIT = frozenset(["queremos", "quisieremos", "creemos"])
# Tercera persona del futuro ("el PSOE aprobara", "o BNG defendera"): solo cuenta si la frase nombra al
# partido. Se mira con tildes: sin ellas, "para" o "cara" parecerian futuros.
_THIRD = re.compile(r"\b\w{3,}(?:ará|erá|irá)\b")
_SENTENCE = re.compile(r"(?<=[.;:!?])\s+|\s*[\n•●▪–]\s*")


@dataclass(frozen=True)
class Candidate:
    actor: str
    country: str
    url: str
    title: str
    found_on: str
    election_kind: str
    election_year: int


def url_hash(url: str) -> str:
    return hashlib.sha256(url.encode()).hexdigest()


def _text(markup: str) -> str:
    return re.sub(r"\s+", " ", _TAGS.sub(" ", markup)).strip()


def election_of(url: str, text: str) -> tuple[str, int] | None:
    """(tipo, ano) de un enlace a un programa, o None si no lo dice."""
    raw = normalize(f"{text} {url.rsplit('/', 1)[-1]} {url}")
    for short, value in _SHORT.items():
        if re.search(rf"(?<![a-z0-9]){re.escape(short)}(?![a-z0-9])", raw):
            return value
    years = _YEAR.findall(normalize(text)) or _YEAR.findall(raw)
    if not years:
        return None
    year = int(years[0])
    for kind, rx in _KIND_WORDS:
        if rx.search(raw):
            return kind, year
    return None


def links(html: str, base: str) -> list[tuple[str, str]]:
    return [(urljoin(base, href.strip()), _text(label)) for href, label in _LINK.findall(html)]


def program_links(actor: ActorSpec, page_url: str, html: str, program_page: bool) -> list[Candidate]:
    """PDF de programas enlazados desde una pagina del partido."""
    out = []
    for url, label in links(html, page_url):
        if not urlsplit(url).path.lower().endswith(".pdf"):
            continue
        said = normalize(f"{label} {url}")
        if not program_page and not _PROGRAM_WORD.search(said):
            continue
        which = election_of(url, label)
        if not which:
            continue
        title = label if len(label) > 6 else url.rsplit("/", 1)[-1]
        out.append(Candidate(actor.slug, actor.country, url, title[:300], page_url, which[0], which[1]))
    return out


def program_pages(actor: ActorSpec, html: str, base: str) -> list[str]:
    """Paginas del mismo sitio que la portada enlaza como programas."""
    host = urlsplit(base).netloc.removeprefix("www.")
    out = []
    for url, label in links(html, base):
        if urlsplit(url).netloc.removeprefix("www.") != host or url.lower().endswith(".pdf"):
            continue
        if _PROGRAM_WORD.search(normalize(f"{label} {urlsplit(url).path.replace('-', ' ')}")):
            out.append(url.split("#")[0])
    return list(dict.fromkeys(out))


@lru_cache(maxsize=1)
def _registry_pages() -> dict[str, tuple[str, ...]]:
    raw = registry._load_yaml(registry.REGISTRY_DIR / "elections.yaml").get("program_pages") or {}
    return {slug: tuple(urls) for slug, urls in raw.items()}


async def discover(client: PoliteClient, actor: ActorSpec) -> tuple[list[Candidate], str | None]:
    """Programas enlazados en la web del partido; el motivo si no se pudo leer."""
    found: list[Candidate] = []
    try:
        resp = await client.get(actor.homepage)
    except Exception as exc:  # red: se dice y se sigue
        return [], f"error de red: {type(exc).__name__}"
    if resp is None:
        return [], "robots.txt no permite leer la portada"
    if resp.status_code != 200 or len(resp.text) < 1000:
        return [], f"la portada responde {resp.status_code} ({len(resp.text)} bytes)"
    base = str(resp.url)
    found += program_links(actor, base, resp.text, program_page=False)
    listed = _registry_pages().get(actor.slug, ())
    pages = list(dict.fromkeys([*listed, *program_pages(actor, resp.text, base)]))
    for page in pages[:MAX_PAGES_TO_VISIT]:
        try:
            r = await client.get(page)
        except Exception:
            continue
        if r is not None and r.status_code == 200:
            found += program_links(actor, str(r.url), r.text, program_page=True)
    unique = {c.url: c for c in found}
    return list(unique.values()), None


def pdf_text(data: bytes) -> tuple[list[str], int]:
    """Texto por pagina de un PDF (hasta MAX_PAGES) y su numero total de paginas."""
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data))
    pages = []
    for page in reader.pages[:MAX_PAGES]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:  # una pagina rota no tumba el documento
            pages.append("")
    return pages, len(reader.pages)


@lru_cache(maxsize=1)
def _topics() -> dict[str, tuple[str, ...]]:
    raw = registry._load_yaml(registry.REGISTRY_DIR / "elections.yaml").get("promise_topics") or {}
    return {slug: tuple(normalize(w) for w in words) for slug, words in raw.items()}


def topic_of(text: str) -> str | None:
    t = normalize(text)
    scores = {
        slug: sum(1 for w in words if re.search(rf"\b{re.escape(w)}\b", t))
        for slug, words in _topics().items()
    }
    best = max(scores.values(), default=0)
    return next(s for s, n in scores.items() if n == best) if best else None


def is_commitment(sentence: str, names: tuple[str, ...] = ()) -> bool:
    t = normalize(sentence)
    if any(m.group(0) not in _NOT_COMMIT for m in _COMMIT.finditer(t)):
        return True
    return bool(names) and bool(_THIRD.search(sentence.lower())) and any(
        re.search(rf"\b{re.escape(n)}\b", t) for n in names
    )


def party_names(slug: str) -> tuple[str, ...]:
    """Como se nombra a un partido en su propio texto (siglas y nombre, sin tildes)."""
    for a in load_political():
        if a.slug == slug:
            return tuple(dict.fromkeys(normalize(n) for n in (a.name, a.full_name) if n))
    return ()


def promises_in(
    pages: list[str], limit: int = MAX_PROMISES, names: tuple[str, ...] = ()
) -> list[tuple[int, str]]:
    """(pagina, frase) de los compromisos de un documento, en orden y sin repetidos."""
    out, seen = [], set()
    for number, page in enumerate(pages, 1):
        flat = re.sub(r"-\n(?=[a-záéíóúñ])", "", page)  # palabras partidas al final de linea
        flat = re.sub(r"(?<![.;:!?])\n(?=[a-záéíóúñ(])", " ", flat)
        for raw in _SENTENCE.split(flat):
            s = re.sub(r"\s+", " ", raw).strip(" -·*")
            if not 50 <= len(s) <= 500 or not is_commitment(s, names):
                continue
            key = normalize(s)
            if key in seen:
                continue
            seen.add(key)
            out.append((number, s))
            if len(out) >= limit:
                return out
    return out


def _save_promises(session: Session, prog: Program, found: list[tuple[int, str]], made_at: datetime) -> int:
    existing = set(session.scalars(select(Promise.text_hash).where(Promise.actor == prog.actor)))
    n = 0
    for page, text in found:
        h = url_hash(normalize(text))
        if h in existing:
            continue
        existing.add(h)
        session.add(
            Promise(
                program_id=prog.id,
                actor=prog.actor,
                country=prog.country,
                election_kind=prog.election_kind,
                election_year=prog.election_year,
                text=text,
                text_hash=h,
                page=page,
                topic=topic_of(text),
                made_at=made_at,
            )
        )
        n += 1
    return n


def store(session: Session, cands: list[Candidate], now: datetime) -> int:
    """Programas nuevos (por URL); devuelve cuantos."""
    known = set(session.scalars(select(Program.url_hash)))
    n = 0
    for c in cands:
        h = url_hash(c.url)
        if h in known:
            continue
        known.add(h)
        session.add(
            Program(
                actor=c.actor,
                country=c.country,
                election_kind=c.election_kind,
                election_year=c.election_year,
                title=c.title,
                url=c.url,
                url_hash=h,
                found_on=c.found_on,
                found_at=now,
            )
        )
        n += 1
    session.flush()
    return n


async def import_one(client: PoliteClient, session: Session, prog: Program, now: datetime) -> str:
    """Descarga y analiza un programa; devuelve el estado que queda."""
    try:
        resp = await client.get(prog.url)
    except Exception as exc:
        prog.status, prog.note = "error", f"error de red: {type(exc).__name__}"[:300]
        return prog.status
    prog.fetched_at = now
    if resp is None:
        prog.status, prog.note = "bloqueado", "robots.txt no permite descargarlo; se enlaza"
        return prog.status
    data = resp.content
    if resp.status_code != 200 or not data.startswith(b"%PDF") or len(data) > MAX_PDF_BYTES:
        prog.status = "error"
        prog.note = f"respuesta {resp.status_code}, {len(data)} bytes, no es un PDF legible"[:300]
        return prog.status
    try:
        pages, total = pdf_text(data)
    except Exception as exc:
        prog.status, prog.note = "error", f"PDF ilegible: {type(exc).__name__}"[:300]
        return prog.status
    prog.content_sha256 = hashlib.sha256(data).hexdigest()
    prog.n_pages = total
    prog.text = "\f".join(pages)
    prog.status = "importado"
    found = promises_in(pages, names=party_names(prog.actor))
    made_at = datetime(prog.election_year, 1, 1, tzinfo=UTC) if prog.election_year else now
    n = _save_promises(session, prog, found, min(made_at, now))
    prog.note = f"{n} promesas extraidas por reglas"
    return prog.status


def statement_promises(session: Session, since: datetime, country: str) -> int:
    """Compromisos de las declaraciones de los canales oficiales desde `since` (ventana electoral)."""
    rows = session.scalars(
        select(PoliticalStatement).where(
            PoliticalStatement.country == country, PoliticalStatement.published_at >= since
        )
    ).all()
    existing = {(a, h) for a, h in session.execute(select(Promise.actor, Promise.text_hash))}
    n = 0
    for st in rows:
        for _, text in promises_in([st.summary or st.text], limit=5, names=party_names(st.actor)):
            h = url_hash(normalize(text))
            if (st.actor, h) in existing:
                continue
            existing.add((st.actor, h))
            session.add(
                Promise(
                    statement_id=st.id,
                    actor=st.actor,
                    country=st.country,
                    text=text,
                    text_hash=h,
                    topic=topic_of(text),
                    made_at=st.published_at,
                )
            )
            n += 1
    return n


_last_discovery: dict[str, float] = {}


def run(session: Session, settings: Settings, windows: list | None = None, clock=time.monotonic) -> dict:
    """Paso del worker: descubrir (cada 6 h por partido), importar unos pocos y extraer promesas."""
    now = datetime.now(UTC)
    actors = load_political()
    every = DISCOVER_EVERY.total_seconds()
    due = [a for a in actors if clock() - _last_discovery.get(a.slug, -1e18) >= every]
    summary: dict = {"discovered": 0, "new_programs": 0, "imported": 0, "unread": {}, "statement_promises": 0}

    async def go():
        async with PoliteClient(settings.user_agent, per_domain_delay=1.0, timeout=60) as client:
            for a in due:
                cands, why = await discover(client, a)
                _last_discovery[a.slug] = clock()
                summary["discovered"] += len(cands)
                if why:
                    summary["unread"][a.slug] = why
                summary["new_programs"] += store(session, cands, now)
            pending = session.scalars(
                select(Program)
                .where(Program.status == "enlazado")
                .order_by(Program.election_year.desc(), Program.id)
                .limit(IMPORTS_PER_RUN)
            ).all()
            for prog in pending:
                if await import_one(client, session, prog, now) == "importado":
                    summary["imported"] += 1

    asyncio.run(go())
    for since, country in windows or []:
        summary["statement_promises"] += statement_promises(session, since, country)
    log.info("programas y promesas: %s", summary)
    return summary
