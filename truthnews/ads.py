"""Cliente de ads-service (microservices-ecosystem): pide anuncios por contexto y nunca rompe la pagina.

La plataforma de publicidad (anunciantes, campanas, subasta, medicion) vive fuera de este repositorio;
aqui solo se pide `POST /ads/v1/serve` con el contexto de la pagina. Sin ADS_SERVICE_URL no se llama a
nada. Cualquier error, respuesta lenta (>150 ms) o mal formada equivale a "sin anuncios". Sin cookies ni
perfiles: el `viewer` es un hash diario opaco calculado en memoria que no se guarda en ningun sitio.
"""

from __future__ import annotations

import hashlib
import ipaddress
import logging
import re
import secrets
import threading
import time
from collections import Counter
from collections.abc import Iterable
from datetime import UTC, datetime
from urllib.parse import urlsplit

import httpx

from truthnews.analysis.text import STOPWORDS
from truthnews.classify import normalize

log = logging.getLogger(__name__)

SLOTS = ("story-inline", "list-native", "footer-strip")
FORMATS = ("text", "native", "strip")
TIMEOUT_SECONDS = 0.15
ERROR_TTL_SECONDS = 60.0
BREAKER_FAILURES = 3
BREAKER_OPEN_SECONDS = 60.0
MAX_KEYWORDS = 8
_WORD = re.compile(r"[a-z][a-z0-9]+")
_TEXT_FIELDS = ("label", "headline", "body", "cta", "display_url", "why")
# Neutralidad (direccion, 2026-10-19): sin publicidad politica, de partidos, gobiernos ni administraciones,
# y ninguna pagina sobre elecciones lleva anuncios. Se comprueba sobre texto normalizado (sin tildes).
_POLITICAL_CATEGORIES = frozenset(
    [
        "politica",
        "political",
        "partido",
        "party",
        "electoral",
        "election",
        "gobierno",
        "government",
        "administracion",
        "administration",
        "institucional",
        "institutional",
        "causa",
        "cause",
        "advocacy",
    ]
)
_POLITICAL_AD = re.compile(
    r"\b(partido|partidos|elecciones|electoral|electorales|vota|votar|votad|voto|votos|candidat\w*|"
    r"campana electoral|gobierno|ministerio|ayuntamiento|junta de|generalitat|xunta|diputacion|"
    r"consejeria|cabildo|administracion publica|psoe|pp|vox|sumar|podemos|erc|junts|bildu|pnv|bng)\b"
)
_ELECTION_PAGE = re.compile(
    r"\b(elecciones|electoral|electorales|comicios|campana electoral|candidat\w*|investidura|"
    r"sondeo\w*|encuesta electoral|mitin\w*|escrutinio|papeletas?|urnas?)\b"
)


def keywords(texts: Iterable[str], limit: int = MAX_KEYWORDS) -> list[str]:
    """Palabras clave del contenido (mismas normalizacion y palabras vacias que el analisis), sin raices."""
    counts: Counter[str] = Counter()
    for text in texts:
        for tok in _WORD.findall(normalize(text or "")):
            if len(tok) >= 4 and tok not in STOPWORDS:
                counts[tok] += 1
    return [w for w, _ in counts.most_common(limit)]


def sensitive(texts: Iterable[str]) -> bool:
    """La pagina trata de elecciones o campanas: no lleva publicidad (ni se pide)."""
    return any(_ELECTION_PAGE.search(normalize(t or "")) for t in texts)


def _political(ad: dict, adv: dict) -> bool:
    if str(adv.get("category") or ad.get("category") or "").strip().lower() in _POLITICAL_CATEGORIES:
        return True
    text = " ".join(str(ad.get(k) or "") for k in ("headline", "body", "cta", "display_url"))
    return bool(_POLITICAL_AD.search(normalize(f"{text} {adv.get('name') or ''}")))


def _same_host(a: str, b: str) -> bool:
    return bool(a and b) and urlsplit(a).hostname == urlsplit(b).hostname


def _truncate_ip(raw: str) -> str:
    try:
        ip = ipaddress.ip_address(raw.strip())
    except ValueError:
        return ""
    prefix = 24 if ip.version == 4 else 48
    return str(ipaddress.ip_network(f"{ip}/{prefix}", strict=False).network_address)


class _DailySalt:
    """Sal aleatoria que cambia cada dia (UTC) y solo existe en memoria: el hash no se puede reconstruir."""

    def __init__(self) -> None:
        self._day = ""
        self._salt = b""
        self._lock = threading.Lock()

    def get(self, now: datetime | None = None) -> bytes:
        day = (now or datetime.now(UTC)).strftime("%Y-%m-%d")
        with self._lock:
            if day != self._day:
                self._day, self._salt = day, secrets.token_bytes(32)
            return self._salt


_salt = _DailySalt()


def viewer_hash(ip: str, user_agent: str, now: datetime | None = None) -> str:
    """sha256(sal diaria + IP truncada a /24 (/48 en IPv6) + User-Agent): opaco y distinto cada dia."""
    h = hashlib.sha256()
    h.update(_salt.get(now))
    h.update(_truncate_ip(ip).encode())
    h.update(b"|")
    h.update((user_agent or "").encode("utf-8", "replace"))
    return h.hexdigest()


def client_ip(headers, peer: str | None) -> str:
    """IP del lector detras del proxy de Railway (primer salto de X-Forwarded-For)."""
    fwd = headers.get("x-forwarded-for", "")
    return fwd.split(",")[0].strip() if fwd else (peer or "")


def _https(url: object) -> bool:
    return isinstance(url, str) and url.startswith("https://") and len(url) < 2048


def _clean_ad(ad: object) -> dict | None:
    """Solo pasa un anuncio completo: etiqueta, enlaces https y formato conocido. Lo demas se descarta."""
    if not isinstance(ad, dict):
        return None
    if not (_https(ad.get("click_url")) and _https(ad.get("view_url"))):
        return None
    if not isinstance(ad.get("headline"), str) or not ad["headline"].strip():
        return None
    adv = ad.get("advertiser") if isinstance(ad.get("advertiser"), dict) else {}
    if _political(ad, adv):
        return None
    out = {k: str(ad.get(k) or "").strip()[:400] for k in _TEXT_FIELDS}
    # La etiqueta es obligatoria por ley (LSSI art. 20): si el servicio no la manda, la ponemos nosotros.
    out["label"] = out["label"] or "Publicidad"
    out.update(
        ad_id=str(ad.get("ad_id") or ""),
        format=ad.get("format") if ad.get("format") in FORMATS else "native",
        click_url=ad["click_url"],
        view_url=ad["view_url"],
        # Sin rastreadores de terceros: la imagen solo se carga si la sirve el mismo host que el clic.
        image_url=ad["image_url"]
        if _https(ad.get("image_url")) and _same_host(ad["image_url"], ad["click_url"])
        else "",
        advertiser={
            "name": str(adv.get("name") or "")[:120],
            "kind": "own" if adv.get("kind") == "own" else "third",
            "group_disclosure": str(adv.get("group_disclosure") or "")[:160],
        },
    )
    return out


class AdsClient:
    """Llama a ads-service con limite de 150 ms, cache de errores de 60 s y cortacircuitos."""

    def __init__(
        self,
        base_url: str,
        site_key: str,
        site: str = "nosmienten",
        transport: httpx.BaseTransport | None = None,
        clock=time.monotonic,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.site_key = site_key
        self.site = site
        self._clock = clock
        self._failures = 0
        self._open_until = 0.0
        self._errors: dict[tuple, float] = {}
        self._lock = threading.Lock()
        self._http = (
            httpx.Client(timeout=httpx.Timeout(TIMEOUT_SECONDS), transport=transport)
            if self.enabled
            else None
        )

    @property
    def enabled(self) -> bool:
        return bool(self.base_url and self.site_key)

    def _skip(self, key: tuple) -> bool:
        now = self._clock()
        with self._lock:
            if now < self._open_until:
                return True
            until = self._errors.get(key)
            if until is not None and now < until:
                return True
            self._errors.pop(key, None)
            return False

    def _failed(self, key: tuple) -> None:
        now = self._clock()
        with self._lock:
            self._failures += 1
            if len(self._errors) > 2000:
                self._errors.clear()
            self._errors[key] = now + ERROR_TTL_SECONDS
            if self._failures >= BREAKER_FAILURES:
                self._open_until = now + BREAKER_OPEN_SECONDS
                self._failures = 0

    def _ok(self) -> None:
        with self._lock:
            self._failures = 0

    def serve(self, slots: Iterable[str], context: dict, viewer: str) -> dict[str, dict]:
        """Anuncios por hueco ({hueco: anuncio}); los huecos sin anuncio no aparecen. Nunca lanza."""
        wanted = [s for s in slots if s in SLOTS]
        if not self.enabled or not wanted:
            return {}
        key = (context.get("url", ""), tuple(context.get("keywords", ())), tuple(wanted))
        if self._skip(key):
            return {}
        body = {
            "site": self.site,
            "slots": wanted,
            "context": context,
            "exclude_advertisers": [],
            "viewer": viewer,
        }
        start = self._clock()
        try:
            r = self._http.post(
                f"{self.base_url}/ads/v1/serve", json=body, headers={"X-Site-Key": self.site_key}
            )
            if self._clock() - start > TIMEOUT_SECONDS:
                raise httpx.TimeoutException("ads-service supera 150 ms")
            r.raise_for_status()
            data = r.json()
            ads = data.get("ads") if isinstance(data, dict) else None
            if not isinstance(ads, dict):
                raise ValueError("respuesta sin 'ads'")
        except Exception as exc:  # cualquier fallo: la pagina se sirve sin anuncios
            log.info("ads-service sin anuncios: %s", exc)
            self._failed(key)
            return {}
        self._ok()
        out = {}
        for slot in wanted:
            ad = _clean_ad(ads.get(slot))
            if ad:
                out[slot] = ad
        return out


def page_context(
    url: str, title: str, category: str | None, texts: Iterable[str], country: str, language: str
) -> dict:
    return {
        "url": url,
        "title": (title or "")[:300],
        "category": category or "",
        "keywords": keywords([title, *texts]),
        "country": country,
        "language": language,
    }
