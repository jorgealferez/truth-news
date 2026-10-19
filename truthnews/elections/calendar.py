"""Calendario electoral automatico (ADR 0036): registro, convocatorias del BOE y elecciones en los medios.

Sin tablas. Tres fuentes, de mas a menos autoridad:

1. El BOE: cada sumario diario se recorre buscando decretos de convocatoria; del texto del decreto se leen
   la fecha de la votacion, la campana y la sesion constitutiva. Una eleccion asi es `convocada` y cita su
   decreto.
2. El registro `registry/elections.yaml`: lo comprobado por una persona con su fuente oficial (y los
   enlaces a los programas). Tambien `convocada`.
3. Los medios rastreados: titulares que nombran unas elecciones, un pais del registro y una fecha. Hacen
   falta al menos MIN_OUTLETS medios distintos con el mismo pais y la misma fecha; se marcan `anunciada`
   y citan esos titulares, nunca se presentan como oficiales.

Una eleccion esta en ventana desde su convocatoria (o su primer titular) hasta POST_DAYS dias despues de
votar; fuera de ventana la seccion no se ensena.
"""

from __future__ import annotations

import html
import re
import threading
import time
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime, timedelta
from functools import lru_cache
from urllib.parse import urljoin

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from truthnews import registry
from truthnews.classify import normalize
from truthnews.data import client
from truthnews.elections import candidacies as cands
from truthnews.models import Article

SUMARIO = "https://www.boe.es/datosabiertos/api/boe/sumario/{:%Y%m%d}"
# Junta Electoral Central: "Elecciones en curso" de todos los ambitos de Espana. Su robots.txt pide
# visitas entre las 20:00 y las 06:59 (Visit-time) y 2 s entre peticiones: una al dia, en esa franja.
JEC = "https://www.juntaelectoralcentral.es/cs/jec/elecciones/actuales"
JEC_HOURS = (20, 7)
JEC_EVERY = 12 * 3600
TEXT = "https://www.boe.es/diario_boe/txt.php?id={}"
POST_DAYS = 30
PRESS_DAYS = 21
MIN_OUTLETS = 2
REFRESH_SECONDS = 1800  # un ciclo del worker
RETRY_SECONDS = 600
KINDS = ("generales", "autonomicas", "locales", "europeas", "presidenciales", "legislativas", "referendum")
_MONTH_NAMES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)
MONTHS = {m: i for i, m in enumerate(_MONTH_NAMES, 1)}
_MONTH = "(" + "|".join(MONTHS) + ")"
_CONVENE = re.compile(
    r"\b(convocatoria de (las )?elecciones|se convocan elecciones|convoca(n)? elecciones)\b"
)
# Organos que se eligen: sin uno de ellos, "elecciones" es otra cosa (sindicales, colegios, camaras...).
_SCOPE = (
    ("europeas", re.compile(r"parlamento europeo")),
    ("generales", re.compile(r"congreso de los diputados")),
    ("locales", re.compile(r"elecciones (locales|municipales)|ayuntamiento|cabildo|concejo")),
    (
        "autonomicas",
        re.compile(r"\b(parlamento|parlament|cortes|corts|asamblea|juntas generales)\b"),
    ),
)
# "...nuevas elecciones locales en el municipio de Villanueva..." (parciales); las generales no tienen sitio.
_DECREE = re.compile(r"Real Decreto (\d+/\d{4})")
_LOCAL_PLACE = re.compile(r"\ben (?:el municipio de |la entidad local menor de )([A-ZÁÉÍÓÚÑ][^,.()]+)")
_POLL_DAY = re.compile(
    rf"celebrar[a-z]*\s+el\s+(?:dia\s+)?(?:[a-z]+\s+)?(?:dia\s+)?(\d{{1,2}})\s+de\s+{_MONTH}(?:\s+de\s+(\d{{4}}))?"
)
_CAMPAIGN = re.compile(
    rf"comenzando a las cero horas del (?:dia\s+)?(?:[a-z]+\s+)?(\d{{1,2}}) de {_MONTH}(?: de (\d{{4}}))?"
    rf".{{0,120}}?finalizando a las veinticuatro horas del (?:dia\s+)?(?:[a-z]+\s+)?(\d{{1,2}}) de {_MONTH}"
    rf"(?: de (\d{{4}}))?"
)
_CONSTITUTION = re.compile(
    rf"sesion(?:es)? constitutiva[s]?[^.]{{0,160}}?el dia (\d{{1,2}})(?: de {_MONTH}(?: de (\d{{4}}))?)?"
)
_PRESS_WORDS = re.compile(
    r"\b(elecciones|comicios|elections|eleicoes|elezioni|wahlen|presidenciales|legislativas)\b"
)
_PRESS_DATE = re.compile(rf"\b(\d{{1,2}}) de {_MONTH}(?: de (\d{{4}}))?")
_PRESS_KIND = (
    ("presidenciales", re.compile(r"presidencial")),
    ("legislativas", re.compile(r"legislativ|parlamentari")),
    ("europeas", re.compile(r"europeas")),
    ("locales", re.compile(r"municipal|locales")),
    ("autonomicas", re.compile(r"autonomic|regional")),
    ("referendum", re.compile(r"referendum|plebiscito")),
)


@dataclass(frozen=True)
class Source:
    label: str
    url: str


@dataclass(frozen=True)
class Election:
    country: str
    kind: str
    date: date
    name: str
    status: str  # convocada (fuente oficial) | anunciada (solo medios)
    sources: tuple[Source, ...]
    region: str | None = None
    place: str | None = None
    convened: date | None = None
    campaign: tuple[date, date] | None = None
    constitution: date | None = None
    programs: dict = field(default_factory=dict, hash=False, compare=False)

    @property
    def slug(self) -> str:
        where = (self.region or "").lower().replace(f"{self.country.lower()}-", "")
        parts = [self.country.lower(), self.kind, where, self.date.isoformat()]
        return "-".join(p for p in parts if p)

    @property
    def key(self) -> tuple:
        return (self.country, self.kind, self.region, self.date)

    def opens(self) -> date:
        return self.convened or self.date - timedelta(days=60)

    def in_window(self, today: date) -> bool:
        return self.opens() <= today <= self.date + timedelta(days=POST_DAYS)

    def phase(self, today: date) -> str:
        if today > self.date:
            return "celebrada"
        if today == self.date:
            return "jornada"
        if self.campaign and self.campaign[0] <= today <= self.campaign[1]:
            return "campana"
        if self.campaign and today == self.campaign[1] + timedelta(days=1):
            return "reflexion"
        return "precampana"

    def days_left(self, today: date) -> int:
        return (self.date - today).days


def _date(day: str, month: str, year: str | None, default_year: int) -> date | None:
    try:
        return date(int(year) if year else default_year, MONTHS[month], int(day))
    except ValueError:
        return None


def plain(markup: str) -> str:
    """Texto normalizado (minusculas, sin tildes, espacios simples) de un HTML del BOE."""
    text = html.unescape(re.sub(r"<[^>]+>", " ", markup))
    return re.sub(r"\s+", " ", normalize(text)).strip()


def scope_of(title: str) -> str | None:
    t = normalize(title)
    if not _CONVENE.search(t):
        return None
    for kind, rx in _SCOPE:
        if rx.search(t):
            return kind
    return None


@lru_cache(maxsize=1)
def _aliases() -> dict[str, tuple[str, ...]]:
    raw = registry._load_yaml(registry.REGISTRY_DIR / "elections.yaml").get("region_aliases") or {}
    return {code: tuple(names) for code, names in raw.items()}


def region_of(text: str) -> str | None:
    t = normalize(text)
    hits = [
        code
        for code, names in _aliases().items()
        if any(re.search(rf"\b{re.escape(n)}\b", t) for n in names)
    ]
    return hits[0] if len(hits) == 1 else None


def parse_decree(text: str, published: date) -> dict:
    """Fecha de votacion, campana y constitucion del texto de un decreto de convocatoria (o {})."""
    t = plain(text) if "<" in text else re.sub(r"\s+", " ", normalize(text))
    m = _POLL_DAY.search(t)
    if not m:
        return {}
    poll = _date(m.group(1), m.group(2), m.group(3), published.year)
    if poll and poll < published:
        poll = _date(m.group(1), m.group(2), str(published.year + 1), published.year)
    if not poll:
        return {}
    out: dict = {"date": poll}
    c = _CAMPAIGN.search(t)
    if c:
        start = _date(c.group(1), c.group(2), c.group(3), poll.year)
        end = _date(c.group(4), c.group(5), c.group(6), poll.year)
        if start and end and start <= end <= poll:
            out["campaign"] = (start, end)
    k = _CONSTITUTION.search(t)
    if k:
        month = k.group(2) or [m for m, i in MONTHS.items() if i == poll.month][0]
        when = _date(k.group(1), month, k.group(3), poll.year)
        if when and when > poll:
            out["constitution"] = when
    return out


def _list(node) -> list:
    if node is None:
        return []
    return node if isinstance(node, list) else [node]


def sumario_items(payload: dict) -> list[dict]:
    """Disposiciones del sumario con su departamento y su epigrafe (para reconocer el territorio)."""
    items: list[dict] = []

    def add(it, dept: str, heading: str):
        if isinstance(it, dict) and "titulo" in it:
            ident = it.get("identificador", "")
            items.append(
                {
                    "id": ident,
                    "titulo": it["titulo"],
                    "url": it.get("url_html") or TEXT.format(ident),
                    "departamento": dept,
                    "epigrafe": heading,
                }
            )

    for diario in _list(payload.get("data", {}).get("sumario", {}).get("diario")):
        for sec in _list(diario.get("seccion")):
            for dep in _list(sec.get("departamento")):
                name = dep.get("nombre", "")
                for ep in _list(dep.get("epigrafe")):
                    for it in _list(ep.get("item")):
                        add(it, name, ep.get("nombre", ""))
                for it in _list(dep.get("item")):
                    add(it, name, "")
    return items


def convocations(payload: dict) -> list[dict]:
    """Decretos de convocatoria de elecciones del sumario, con su ambito y su territorio."""
    out = []
    for it in sumario_items(payload):
        kind = scope_of(it["titulo"])
        if not kind:
            continue
        region = None if kind in ("generales", "europeas") else region_of(
            f"{it['titulo']} {it['departamento']} {it['epigrafe']}"
        )
        out.append({**it, "kind": kind, "region": region})
    return out


def from_boe(item: dict, decree_text: str, published: date) -> Election | None:
    data = parse_decree(decree_text, published)
    if not data:
        return None
    kind, region = item["kind"], item["region"]
    place = None
    if kind == "locales":
        m = _LOCAL_PLACE.search(item["titulo"])
        place = m.group(1).strip() if m else None
    return Election(
        country="ES",
        kind=kind,
        date=data["date"],
        name=default_name(kind, region, place, "ES"),
        status="convocada",
        sources=(Source(f"{item['titulo']} ({item['id']})", item["url"]),),
        region=region,
        place=place,
        convened=published,
        campaign=data.get("campaign"),
        constitution=data.get("constitution"),
    )


_JEC_ITEM = re.compile(r"<li>\s*<a[^>]*href=\"([^\"]+)\"[^>]*>([^<]+)</a>", re.S)
_JEC_DATE = re.compile(rf"(\d{{1,2}}) de {_MONTH} de (\d{{4}})")


def jec_in_window(hour: int) -> bool:
    start, end = JEC_HOURS
    return hour >= start or hour < end


def from_jec(markup: str) -> list[Election]:
    """Elecciones en curso segun la Junta Electoral Central (nombre del organo y fecha de votacion)."""
    i = markup.find("Elecciones en curso</h3>")
    out = []
    for href, label in _JEC_ITEM.findall(markup[i:] if i >= 0 else markup):
        label = html.unescape(re.sub(r"\s+", " ", label)).strip()
        t = normalize(label)
        m = _JEC_DATE.search(t)
        if not m:
            continue
        when = _date(m.group(1), m.group(2), m.group(3), int(m.group(3)))
        if "generales" in t:
            kind = "generales"
        elif "europe" in t:
            kind = "europeas"
        elif "locales" in t or "municipales" in t:
            kind = "locales"
        elif re.search(r"\b(parlamento|parlament|cortes|corts|asamblea|junta general)\b", t):
            kind = "autonomicas"
        else:
            continue
        region = region_of(label) if kind == "autonomicas" else None
        if kind == "autonomicas" and not region:
            continue
        out.append(
            Election(
                country="ES",
                kind=kind,
                date=when,
                name=default_name(kind, region, None, "ES"),
                status="convocada",
                sources=(Source(f"Junta Electoral Central: {label}", urljoin(JEC, href)),),
                region=region,
            )
        )
    return out


def default_name(kind: str, region: str | None, place: str | None, country: str) -> str:
    base = {
        "generales": "Elecciones generales",
        "autonomicas": "Elecciones autonómicas",
        "locales": "Elecciones locales",
        "europeas": "Elecciones al Parlamento Europeo",
        "presidenciales": "Elecciones presidenciales",
        "legislativas": "Elecciones legislativas",
        "referendum": "Referéndum",
    }.get(kind, "Elecciones")
    where = place or (registry.region_name(region) if region else None)
    if not where and country != "ES":  # Espana es el pais por omision del sitio
        where = registry.country_name(country, "es")
    return f"{base} · {where}" if where else base


def _as_date(value) -> date | None:
    if value is None or isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def load_registry(raw: dict | None = None) -> list[Election]:
    raw = raw if raw is not None else registry._load_yaml(registry.REGISTRY_DIR / "elections.yaml")
    out = []
    for e in raw.get("elections") or []:
        kind = e["kind"]
        if kind not in KINDS:
            raise registry.RegistryError(f"eleccion con tipo desconocido: {kind}")
        campaign = e.get("campaign")
        src = e.get("source") or {}
        if not src.get("url"):
            raise registry.RegistryError(f"eleccion sin fuente oficial: {e.get('name')}")
        out.append(
            Election(
                country=e["country"],
                kind=kind,
                date=_as_date(e["date"]),
                name=e.get("name") or default_name(kind, e.get("region"), e.get("place"), e["country"]),
                status="convocada",
                sources=(Source(src.get("label") or src["url"], src["url"]),),
                region=e.get("region"),
                place=e.get("place"),
                convened=_as_date(e.get("convened")),
                campaign=(_as_date(campaign[0]), _as_date(campaign[1])) if campaign else None,
                constitution=_as_date(e.get("constitution")),
                programs=dict(e.get("programs") or {}),
            )
        )
    return out


@lru_cache(maxsize=1)
def _country_names() -> dict[str, str]:
    """Nombre normalizado (en cualquier idioma del registro) -> ISO, sin los nombres ambiguos de 3 letras."""
    out = {}
    for iso, c in registry.countries().items():
        for name in (c.get("name") or {}).values():
            n = normalize(name)
            if len(n) > 3:
                out[n] = iso
    return out


def press_hits(articles: list, today: date) -> list[Election]:
    """Elecciones que al menos MIN_OUTLETS medios distintos situan en el mismo pais y la misma fecha."""
    groups: dict[tuple[str, date], dict] = {}
    names = _country_names()
    for a in articles:
        t = normalize(a.title)
        if not _PRESS_WORDS.search(t):
            continue
        countries = {iso for n, iso in names.items() if re.search(rf"\b{re.escape(n)}\b", t)}
        dates = []
        for m in _PRESS_DATE.finditer(t):
            d = _date(m.group(1), m.group(2), m.group(3), today.year)
            if d and not m.group(3) and d < today - timedelta(days=POST_DAYS):
                d = _date(m.group(1), m.group(2), str(today.year + 1), today.year)
            if d and today - timedelta(days=POST_DAYS) <= d <= today + timedelta(days=400):
                dates.append(d)
        if len(countries) != 1 or len(set(dates)) != 1:
            continue
        key = (countries.pop(), dates[0])
        g = groups.setdefault(key, {"outlets": set(), "arts": [], "first": a.published_at, "kinds": []})
        g["outlets"].add(a.outlet_id)
        g["arts"].append(a)
        g["first"] = min(g["first"], a.published_at)
        g["kinds"].extend(k for k, rx in _PRESS_KIND if rx.search(t))
    out = []
    for (iso, d), g in groups.items():
        if len(g["outlets"]) < MIN_OUTLETS:
            continue
        kind = max(set(g["kinds"]), key=g["kinds"].count) if g["kinds"] else "generales"
        arts = sorted(g["arts"], key=lambda a: a.published_at)[:5]
        out.append(
            Election(
                country=iso,
                kind=kind,
                date=d,
                name=default_name(kind, None, None, iso),
                status="anunciada",
                sources=tuple(Source(f"{a.title} ({a.outlet.name})", a.url) for a in arts),
                convened=g["first"].date() if isinstance(g["first"], datetime) else None,
            )
        )
    return out


def press_articles(session: Session, now: datetime) -> list:
    since = now - timedelta(days=PRESS_DAYS)
    words = ("%elecci%", "%comicios%", "%election%", "%eleic%", "%elezion%", "%wahl%")
    return list(
        session.scalars(
            select(Article)
            .options(joinedload(Article.outlet))
            .where(Article.published_at >= since, or_(*(Article.title.ilike(w) for w in words)))
            .order_by(Article.published_at.desc())
            .limit(3000)
        )
    )


def merge(*sources: list[Election]) -> list[Election]:
    """Una eleccion por (pais, tipo, territorio, fecha); gana la primera fuente (oficial antes que medios).

    Lo anunciado en medios se descarta si ya hay una eleccion oficial del mismo pais el mismo dia.
    """
    out: dict[tuple, Election] = {}
    for group in sources:
        for e in group:
            if e.status == "anunciada" and any(
                o.country == e.country and o.date == e.date and o.status == "convocada" for o in out.values()
            ):
                continue
            prev = out.get(e.key)
            if prev is None:
                out[e.key] = e
            else:
                out[e.key] = replace(
                    prev,
                    campaign=prev.campaign or e.campaign,
                    constitution=prev.constitution or e.constitution,
                    convened=prev.convened or e.convened,
                    programs={**e.programs, **prev.programs},
                    sources=prev.sources
                    + tuple(s for s in e.sources if s.url not in {p.url for p in prev.sources}),
                )
    return sorted(out.values(), key=lambda e: (e.date, e.country, e.kind, e.region or ""))


class Calendar:
    """Elecciones en ventana, con el BOE barrido en segundo plano y cacheado por dia en memoria."""

    def __init__(
        self,
        lookback_days: int,
        transport: httpx.BaseTransport | None = None,
        clock=time.monotonic,
        background: bool = True,
        registry_raw: dict | None = None,
    ) -> None:
        self.lookback = lookback_days
        self._transport = transport
        self._clock = clock
        self._background = background
        self._registry = load_registry(registry_raw)
        self._days: dict[date, tuple[float, list[Election]]] = {}
        # Candidaturas por decreto de convocatoria ("806/2026"): {kind, id, url, published, formations}.
        self._candidacies: dict[str, dict] = {}
        self._press: tuple[float, list[Election]] = (-1e18, [])
        self._jec: tuple[float, list[Election]] = (-1e18, [])
        self._warmed_at = -1e18
        self._running = False
        self._lock = threading.Lock()

    def _boe_day(self, d: date, today: date) -> list[Election]:
        with self._lock:
            hit = self._days.get(d)
        if hit and (d < today - timedelta(days=2) or self._clock() - hit[0] < RETRY_SECONDS):
            return hit[1]
        found: list[Election] = []
        try:
            with client(self._transport) as c:
                resp = c.get(SUMARIO.format(d), headers={"Accept": "application/json"})
                if resp.status_code == 200:
                    payload = resp.json()
                    self._read_candidacies(c, payload, d)
                    for item in convocations(payload):
                        doc = c.get(TEXT.format(item["id"]))
                        if doc.status_code == 200:
                            e = from_boe(item, doc.text, d)
                            if e:
                                found.append(e)
                elif resp.status_code != 404:  # 404 = no hubo BOE ese dia
                    raise httpx.HTTPError(f"BOE {resp.status_code}")
        except (httpx.HTTPError, ValueError):
            with self._lock:  # se reintenta en RETRY_SECONDS, sin olvidar lo que ya habia
                self._days[d] = (self._clock(), hit[1] if hit else [])
            return hit[1] if hit else []
        with self._lock:
            self._days[d] = (self._clock(), found)
        return found

    def _read_candidacies(self, c: httpx.Client, payload: dict, published: date) -> None:
        """Si el sumario publica candidaturas de una convocatoria, se leen (las proclamadas mandan)."""
        for it in sumario_items(payload):
            kind = cands.kind_of(it["titulo"])
            decree = _DECREE.search(it["titulo"])
            if not kind or not decree:
                continue
            with self._lock:
                prev = self._candidacies.get(decree.group(1))
            if prev and (prev["kind"] == "proclamadas" or prev["id"] == it["id"]):
                continue
            doc = c.get(TEXT.format(it["id"]))
            if doc.status_code != 200:
                continue
            formations = cands.parse(doc.text)
            if formations:
                with self._lock:
                    self._candidacies[decree.group(1)] = {
                        "kind": kind,
                        "id": it["id"],
                        "url": it["url"],
                        "published": published,
                        "formations": formations,
                    }

    def candidacies(self, e: Election) -> dict | None:
        """Candidaturas publicadas en el BOE para la convocatoria de esta eleccion (o None)."""
        for src in e.sources:
            m = _DECREE.search(src.label)
            if m:
                with self._lock:
                    hit = self._candidacies.get(m.group(1))
                if hit:
                    return hit
        return None

    def _read_jec(self, hour: int) -> None:
        if not jec_in_window(hour) or self._clock() - self._jec[0] < JEC_EVERY:
            return
        try:
            with client(self._transport) as c:
                resp = c.get(JEC)
            found = from_jec(resp.text) if resp.status_code == 200 else None
        except httpx.HTTPError:
            found = None
        with self._lock:  # si falla, se conserva lo ultimo bueno y se reintenta en la siguiente franja
            self._jec = (self._clock(), found if found is not None else self._jec[1])

    def warm(self, today: date, pause: float = 0.3, hour: int | None = None) -> None:
        self._read_jec(datetime.now(UTC).hour if hour is None else hour)
        for back in range(self.lookback + 1):
            d = today - timedelta(days=back)
            if d.weekday() == 6:  # los domingos no hay BOE
                continue
            with self._lock:
                hit = self._days.get(d)
            if hit and d < today - timedelta(days=2):
                continue
            self._boe_day(d, today)
            if pause:
                time.sleep(pause)

    def ensure_warm(self, today: date) -> None:
        if self.lookback <= 0:
            return
        with self._lock:
            if self._running or self._clock() - self._warmed_at < REFRESH_SECONDS:
                return
            self._running = True

        def job():
            try:
                self.warm(today, pause=0.3 if self._background else 0)
            finally:
                with self._lock:
                    self._running = False
                    self._warmed_at = self._clock()

        if self._background:
            threading.Thread(target=job, name="elections-boe", daemon=True).start()
        else:
            job()

    def boe(self) -> list[Election]:
        with self._lock:
            return [e for _, items in self._days.values() for e in items]

    def press(self, session: Session | None, now: datetime) -> list[Election]:
        if session is None:
            return self._press[1]
        if self._clock() - self._press[0] < REFRESH_SECONDS:
            return self._press[1]
        found = press_hits(press_articles(session, now), now.date())
        self._press = (self._clock(), found)
        return found

    def all(self, session: Session | None = None, now: datetime | None = None) -> list[Election]:
        now = now or datetime.now(UTC)
        self.ensure_warm(now.date())
        return merge(self.boe(), self._jec[1], self._registry, self.press(session, now))

    def active(self, session: Session | None = None, now: datetime | None = None) -> list[Election]:
        now = now or datetime.now(UTC)
        return [e for e in self.all(session, now) if e.in_window(now.date())]

    def get(self, slug: str, session: Session | None = None, now: datetime | None = None) -> Election | None:
        return next((e for e in self.all(session, now) if e.slug == slug), None)
