"""Contratacion publica para la web: BOE (seccion V.A) y adjudicaciones en TED, en memoria y citadas.

Sin tablas (ADR 0042). Un dia pasado del BOE con datos no cambia y se guarda mientras viva el proceso; las
adjudicaciones de TED de los ultimos `TED_DAYS` dias se piden como mucho cada 6 h (cada 10 min si fallo).
El cruce con las noticias rastreadas solo enlaza menciones del nombre propio de la empresa o del organo:
no afirma relacion alguna entre el contrato y la noticia.
"""

from __future__ import annotations

import re
import threading
import time
from collections import defaultdict
from datetime import date, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from truthnews.classify import normalize
from truthnews.data import contratacion as ct
from truthnews.models import Article

RETRY_SECONDS = 600
TED_REFRESH_SECONDS = 6 * 3600
TED_DAYS = 14
MAX_DAYS_CACHED = 120
LOOKBACK_DAYS = 4
MENTION_DAYS = 60
MENTIONS_PER_NAME = 3
TOP = 15

# Formas juridicas y palabras de relleno que no identifican a una empresa.
_LEGAL = re.compile(
    r"\b(s\.?\s?a\.?\s?u\.?|s\.?\s?l\.?\s?u\.?|s\.?\s?a\.?|s\.?\s?l\.?|s\.?\s?coop\.?|"
    r"sociedad anonima( unipersonal)?|sociedad limitada( unipersonal)?|slp|sll|unipersonal)$",
    re.I,
)
_GENERIC = frozenset(
    [
        "grupo",
        "servicios",
        "servicio",
        "sistemas",
        "soluciones",
        "empresa",
        "compania",
        "espana",
        "espanola",
        "iberica",
        "iberia",
        "consulting",
        "ingenieria",
        "construcciones",
        "obras",
        "gestion",
        "tecnologia",
        "tecnologias",
        "informatica",
        "medical",
        "global",
        "integral",
        "integrales",
        "general",
        "generales",
        "energia",
        "salud",
        "farma",
        "pharma",
        "madrid",
        "barcelona",
    ]
)


def core_name(name: str) -> str:
    """'IDOM CONSULTING ENGINEERING ARCHITECTURE SAU' -> 'idom consulting engineering architecture'."""
    n = normalize(name).replace(",", " ").strip(" .")
    prev = None
    while prev != n:
        prev = n
        n = _LEGAL.sub("", n).strip(" .,-")
    return re.sub(r"\s+", " ", n)


def searchable(core: str) -> bool:
    """Un nombre basta para buscarlo en prensa si no es una UTE y no se reduce a palabras genericas."""
    flat = core.replace(".", "")
    if not core or flat.startswith("ute ") or " ute " in f" {flat} ":
        return False
    words = [w for w in re.findall(r"\w+", core) if w not in _GENERIC and len(w) >= 3]
    return bool(words) and (len(words) >= 2 or len(words[0]) >= 6)


class BoeContractDays:
    def __init__(self, transport: httpx.BaseTransport | None = None, clock=time.monotonic) -> None:
        self._transport = transport
        self._clock = clock
        self._cache: dict[date, tuple[float, list[ct.Anuncio]]] = {}
        self._lock = threading.Lock()

    def day(self, d: date, today: date) -> list[ct.Anuncio]:
        with self._lock:
            hit = self._cache.get(d)
        if hit and ((hit[1] and d < today) or self._clock() - hit[0] < RETRY_SECONDS):
            return hit[1]
        try:
            items = ct.boe_anuncios(d, transport=self._transport)
        except (httpx.HTTPError, ValueError):
            items = []
        with self._lock:
            if len(self._cache) >= MAX_DAYS_CACHED:
                self._cache.clear()
            self._cache[d] = (self._clock(), items)
        return items

    def latest(self, today: date) -> tuple[date, list[ct.Anuncio]]:
        """El BOE mas reciente con anuncios de contratacion (hoy o hasta LOOKBACK_DAYS atras)."""
        for back in range(LOOKBACK_DAYS):
            d = today - timedelta(days=back)
            items = self.day(d, today)
            if items:
                return d, items
        return today, []


class TedAwards:
    """Adjudicaciones de Espana en TED de los ultimos TED_DAYS dias; se conserva la ultima lista buena.

    TED tarda ~25 s en servir ~1.000 avisos (medido 2026-10-19): el refresco va en segundo plano y la pagina
    nunca lo espera; mientras no haya una primera lista, se muestra "no disponible".
    """

    def __init__(
        self, fetch=ct.ted_adjudicaciones, clock=time.monotonic, days: int = TED_DAYS, background: bool = True
    ) -> None:
        self._fetch = fetch
        self._clock = clock
        self.days = days
        self._background = background
        self._value: tuple[date, date, list[ct.Adjudicacion]] | None = None
        self._at = -1e18
        self._running = False
        self._lock = threading.Lock()

    def get(self, today: date) -> tuple[date, date, list[ct.Adjudicacion]] | None:
        with self._lock:
            ttl = TED_REFRESH_SECONDS if self._value else RETRY_SECONDS
            stale = self._clock() - self._at >= ttl
            if not stale or self._running:
                return self._value
            self._running = True
            current = self._value  # lo que habia al pedirlo: el hilo puede terminar antes de devolver

        def job():
            since = today - timedelta(days=self.days)
            try:
                items = self._fetch(since, today)
            except (httpx.HTTPError, ValueError):
                items = []
            with self._lock:
                self._at = self._clock()
                self._running = False
                if items:
                    self._value = (since, today, items)

        if self._background:
            threading.Thread(target=job, name="ted-awards", daemon=True).start()
            return current
        job()
        with self._lock:
            return self._value


def boe_view(items: list[ct.Anuncio]) -> dict:
    by_dep: dict[str, list[ct.Anuncio]] = defaultdict(list)
    for i in items:
        by_dep[i.departamento or "—"].append(i)
    counts: dict[str, int] = defaultdict(int)
    for i in items:
        counts[i.tipo] += 1
    return {
        "deps": sorted(by_dep.items(), key=lambda kv: -len(kv[1])),
        "counts": dict(counts),
        "total": len(items),
    }


def ted_view(items: list[ct.Adjudicacion]) -> dict:
    """Cifras del periodo, empresas que mas importe suman (por nombre sin forma juridica) y contratos mayores.

    El importe de un aviso con varios adjudicatarios (lotes) se atribuye entero a cada uno: se marca como
    'varios' y no se suma al total por empresa para no inflarlo.
    """
    eur = [a for a in items if a.importe is not None and a.moneda == "EUR"]
    firms: dict[str, dict] = {}
    for a in items:
        for name, nif in a.adjudicatarios:
            f = firms.setdefault(
                core_name(name), {"nombre": name, "nif": nif, "contratos": [], "importe": 0.0, "lotes": 0}
            )
            f["nif"] = f["nif"] or nif
            f["contratos"].append(a)
            if a.importe is not None and a.moneda == "EUR":
                if len(a.adjudicatarios) == 1:
                    f["importe"] += a.importe
                else:
                    f["lotes"] += 1
    buyers: dict[str, dict] = {}
    for a in items:
        b = buyers.setdefault(a.comprador or "—", {"nombre": a.comprador or "—", "n": 0, "importe": 0.0})
        b["n"] += 1
        if a.importe is not None and a.moneda == "EUR":
            b["importe"] += a.importe
    return {
        "total": len(items),
        "with_amount": len(eur),
        "amount": sum(a.importe for a in eur),
        "firms": sorted(firms.values(), key=lambda f: (-f["importe"], -len(f["contratos"])))[:TOP],
        "repeat": sorted(
            (f for f in firms.values() if len(f["contratos"]) >= 2), key=lambda f: -len(f["contratos"])
        )[:TOP],
        "buyers": sorted(buyers.values(), key=lambda b: -b["importe"])[:TOP],
        "largest": sorted(eur, key=lambda a: -(a.importe or 0))[:TOP],
    }


def _word(needle: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text) is not None


def _probe(name: str) -> str:
    """Palabra del nombre original para filtrar en la base (la comprobacion fina se hace en Python).

    Se prefiere la mas larga sin tildes: el filtro de la base distingue 'Tecnicos' de 'Técnicos'.
    """
    words = [w for w in re.findall(r"\w+", core_name(name)) if w not in _GENERIC]
    plain = [w for w in re.findall(r"\w+", name) if normalize(w) in words]
    return max(plain, key=lambda w: (w.isascii(), len(w)), default=words[0])


def mentions(session: Session, names: list[str], until) -> dict[str, list[Article]]:
    """Noticias rastreadas de los ultimos 60 dias que nombran a cada empresa u organo (nombre propio)."""
    out: dict[str, list[Article]] = {}
    since = until - timedelta(days=MENTION_DAYS)
    for name in dict.fromkeys(names):
        core = core_name(name)
        if not searchable(core):
            continue
        probe = _probe(name)
        rows = session.scalars(
            select(Article)
            .options(joinedload(Article.outlet))
            .where(
                Article.published_at >= since,
                Article.published_at < until,
                or_(Article.title.ilike(f"%{probe}%"), Article.summary.ilike(f"%{probe}%")),
            )
            .order_by(Article.published_at.desc())
            .limit(50)
        )
        hits = []
        for a in rows:
            if _word(core, normalize(f"{a.title} {a.summary or ''}")):
                hits.append(a)
            if len(hits) == MENTIONS_PER_NAME:
                break
        if hits:
            out[name] = hits
    return out


class CitedFirms:
    """Indice de adjudicatarios de TED por nombre sin forma juridica, reconstruido cuando cambia la lista."""

    def __init__(self, awards: TedAwards) -> None:
        self.awards = awards
        self._built_for: int | None = None
        self._index: list[tuple[re.Pattern, str, list[ct.Adjudicacion]]] = []
        self._lock = threading.Lock()

    def _index_for(self, items: list[ct.Adjudicacion]) -> list[tuple[re.Pattern, str, list[ct.Adjudicacion]]]:
        with self._lock:
            if self._built_for != id(items):
                by_core: dict[str, tuple[str, list[ct.Adjudicacion]]] = {}
                for a in items:
                    for name, _ in a.adjudicatarios:
                        core = core_name(name)
                        if searchable(core):
                            by_core.setdefault(core, (name, []))[1].append(a)
                self._index = [
                    (re.compile(rf"(?<!\w){re.escape(core)}(?!\w)"), name, awards)
                    for core, (name, awards) in by_core.items()
                ]
                self._built_for = id(items)
            return self._index

    def in_texts(self, texts: list[str], today: date, limit: int = MENTIONS_PER_NAME) -> list[dict]:
        """Empresas que la noticia nombra por su nombre completo y que ganaron contratos en TED en el periodo.

        Solo enlaza el dato oficial: no dice que la noticia trate del contrato.
        """
        got = self.awards.get(today)
        text = normalize(" ".join(t for t in texts if t))
        if not got or not text:
            return []
        out = []
        for rx, name, awards in self._index_for(got[2]):
            if rx.search(text):
                eur = [a.importe for a in awards if a.importe is not None and a.moneda == "EUR"]
                out.append(
                    {
                        "nombre": name,
                        "contratos": sorted(awards, key=lambda a: -(a.importe or 0))[:limit],
                        "n": len(awards),
                        "importe": sum(eur) if all(len(a.adjudicatarios) == 1 for a in awards) else None,
                    }
                )
        return sorted(out, key=lambda f: -f["n"])[:5]
