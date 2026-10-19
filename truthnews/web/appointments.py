"""Nombramientos y ceses del BOE para la web: un dia por pagina, cacheado en memoria y citado.

Sin tablas: cada dia se lee del sumario del BOE (truthnews.data.nombramientos). Un dia pasado con datos no
cambia y se guarda mientras viva el proceso; hoy o una respuesta vacia se vuelven a pedir a los 10 min.
"""

from __future__ import annotations

import re
import threading
import time
from datetime import date, timedelta

import httpx
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, joinedload

from truthnews.classify import normalize
from truthnews.data import nombramientos as nb
from truthnews.models import Article

_PARTICLES = frozenset(["de", "del", "la", "las", "los", "el", "y", "e", "para", "con", "en", "a"])
RETRY_SECONDS = 600
MAX_DAYS_CACHED = 120
LOOKBACK_DAYS = 4
MENTION_DAYS = 60
INDEX_REFRESH_SECONDS = 6 * 3600
# Vocabulario de nombramiento o cese: sin el, nombrar a una persona no basta para enlazar su BOE.
_APPOINT_WORDS = re.compile(
    r"\b(nombra\w*|nombramiento\w*|designa\w*|cesa\w*|cese\w*|destitu\w*|relev\w*|sustitu\w*|"
    r"nuev[oa]s? (director|directora|secretari[oa]|subsecretari[oa]|presidente|presidenta|embajador|"
    r"embajadora|fiscal|delegad[oa]|jef[ea]))",
)
MENTIONS_PER_PERSON = 3


class BoeDays:
    def __init__(self, transport: httpx.BaseTransport | None = None, clock=time.monotonic) -> None:
        self._transport = transport
        self._clock = clock
        self._cache: dict[date, tuple[float, list[nb.Disposicion]]] = {}
        self._lock = threading.Lock()

    def day(self, d: date, today: date) -> list[nb.Disposicion]:
        with self._lock:
            hit = self._cache.get(d)
        if hit and ((hit[1] and d < today) or self._clock() - hit[0] < RETRY_SECONDS):
            return hit[1]
        try:
            items = nb.nombramientos(d, transport=self._transport)
        except httpx.HTTPError:
            items = []
        with self._lock:
            if len(self._cache) >= MAX_DAYS_CACHED:
                self._cache.clear()
            self._cache[d] = (self._clock(), items)
        return items

    def cached(self, today: date, days: int) -> list[nb.Disposicion]:
        """Lo ya descargado de los ultimos `days` dias, sin pedir nada (para no bloquear una pagina)."""
        since = today - timedelta(days=days)
        with self._lock:
            return [i for d, (_, items) in self._cache.items() if since <= d <= today for i in items]

    def warm(self, today: date, days: int, pause: float = 0.5) -> None:
        """Descarga los dias que falten (sin domingos, cuando no hay BOE), con pausa entre peticiones."""
        for back in range(days + 1):
            d = today - timedelta(days=back)
            if d.weekday() == 6:
                continue
            with self._lock:
                hit = self._cache.get(d)
            if hit and hit[1] and d < today:
                continue
            self.day(d, today)
            if pause:
                time.sleep(pause)

    def latest(self, today: date) -> tuple[date, list[nb.Disposicion]]:
        """El BOE mas reciente con disposiciones de personal (hoy o hasta LOOKBACK_DAYS atras)."""
        for back in range(LOOKBACK_DAYS):
            d = today - timedelta(days=back)
            items = self.day(d, today)
            if items:
                return d, items
        return today, []


def dept_name(raw: str) -> str:
    """'MINISTERIO DE LA PRESIDENCIA' -> 'Ministerio de la Presidencia' (el BOE los da en mayusculas)."""
    words = raw.lower().split()
    return " ".join(w if (i and w in _PARTICLES) else w.capitalize() for i, w in enumerate(words))


def view(items: list[nb.Disposicion]) -> dict:
    """Primero nombramientos y ceses de una persona, por organo; el resto (colectivos, destinos...) aparte."""
    named: dict[str, list[nb.Disposicion]] = {}
    rest: list[nb.Disposicion] = []
    for i in items:
        if i.tipo in ("nombramiento", "cese") and i.persona:
            named.setdefault(dept_name(i.departamento) or "—", []).append(i)
        else:
            rest.append(i)
    counts = {
        "nombramiento": sum(1 for i in items if i.tipo == "nombramiento"),
        "cese": sum(1 for i in items if i.tipo == "cese"),
        "total": len(items),
    }
    return {"named": sorted(named.items(), key=lambda kv: -len(kv[1])), "rest": rest, "counts": counts}


def _name_keys(persona: str) -> tuple[str, str] | None:
    """Nombre de pila y primer apellido ('María Dolores Rial de la Calle' -> ('María', 'Rial'))."""
    words = [w for w in persona.split() if w.lower() not in _PARTICLES]
    if len(words) < 2:
        return None
    surname = words[-2] if len(words) >= 3 else words[-1]
    return words[0], surname


def _word(needle: str, text: str) -> bool:
    return re.search(rf"(?<!\w){re.escape(needle)}(?!\w)", text) is not None


def mentions(session: Session, people: list[str], until) -> dict[str, list[Article]]:
    """Noticias rastreadas de los ultimos 60 dias que nombran a cada persona (nombre y primer apellido)."""
    out: dict[str, list[Article]] = {}
    since = until - timedelta(days=MENTION_DAYS)
    for persona in dict.fromkeys(people):
        keys = _name_keys(persona)
        if not keys:
            continue
        first, surname = keys
        rows = session.scalars(
            select(Article)
            .options(joinedload(Article.outlet))
            .where(
                Article.published_at >= since,
                or_(Article.title.ilike(f"%{surname}%"), Article.summary.ilike(f"%{surname}%")),
            )
            .order_by(Article.published_at.desc())
            .limit(50)
        )
        nf, ns = normalize(first), normalize(surname)
        hits = []
        for a in rows:
            text = normalize(f"{a.title} {a.summary or ''}")
            if _word(ns, text) and _word(nf, text):
                hits.append(a)
            if len(hits) == MENTIONS_PER_PERSON:
                break
        if hits:
            out[persona] = hits
    return out


class BoeIndex:
    """Nombramientos y ceses de los ultimos dias en memoria, refrescados en segundo plano cada 6 h."""

    def __init__(self, days: BoeDays, window: int, clock=time.monotonic, background: bool = True) -> None:
        self.days = days
        self.window = window
        self._clock = clock
        self._background = background
        self._warmed_at = -1e18
        self._running = False
        self._lock = threading.Lock()

    def ensure_warm(self, today: date) -> None:
        if self.window <= 0:
            return
        with self._lock:
            if self._running or self._clock() - self._warmed_at < INDEX_REFRESH_SECONDS:
                return
            self._running = True

        def job():
            try:
                self.days.warm(today, self.window, pause=0.5 if self._background else 0)
            finally:
                with self._lock:
                    self._running = False
                    self._warmed_at = self._clock()

        if self._background:
            threading.Thread(target=job, name="boe-index", daemon=True).start()
        else:
            job()

    def confirmations(self, texts: list[str], today: date) -> list[nb.Disposicion]:
        """Nombramientos y ceses del BOE reciente de personas que el texto nombra junto a un verbo de cargo.

        Solo confirma: que algo no este en el BOE no se muestra (el BOE publica dias despues del anuncio).
        """
        self.ensure_warm(today)
        text = normalize(" ".join(t for t in texts if t))
        if not text or not _APPOINT_WORDS.search(text):
            return []
        out, seen = [], set()
        for i in self.days.cached(today, self.window):
            if i.tipo not in ("nombramiento", "cese") or not i.persona or i.id in seen:
                continue
            keys = _name_keys(i.persona)
            if keys and _word(normalize(keys[0]), text) and _word(normalize(keys[1]), text):
                seen.add(i.id)
                out.append(i)
        return sorted(out, key=lambda i: i.fecha, reverse=True)[:5]
