"""Consulta puntual de interes publico: navegacion dirigida a un documento concreto (ADR 0029).

Excepcion acotada al ADR 0003, por decision del usuario (2026-10-19). Cuando un documento concreto (p. ej.
una pagina de un portal de transparencia) es imprescindible para contrastar un dato, porque hay dudas entre
medios o faltan pruebas de la entidad, y la fuente no se obtiene por otra via, se permite llegar a ese
documento aunque robots.txt excluya las paginas. Siempre:

- con justificacion y las vias alternativas probadas, o no se consulta;
- solo el dominio de partida y como mucho MAX_PAGES paginas, cada URL registrada con su hora, su estado y lo
  que decia robots.txt;
- con el User-Agent honesto del rastreador, nunca suplantado;
- se para ante 401, 403 o 429 y ante una pagina de desafio (captcha): un bloqueo tecnico no se elude;
- al obtener el documento se para, y nada de lo visitado se reutiliza para seguir rastreando (no hay cola
  ni descubrimiento de enlaces fuera de esta funcion).

La traza completa (`Lookup.as_payload()`) se guarda en la evidencia de la verificacion que la motivo.
"""

from __future__ import annotations

import asyncio
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import urljoin, urlsplit

import httpx

from truthnews.crawler.http import PoliteClient
from truthnews.models import Evidence

MAX_PAGES = 5
JUSTIFICATIONS = ("dudas-entre-medios", "falta-de-pruebas")
BLOCKED = (401, 403, 429)
_CHALLENGE = re.compile(r"captcha|cf-challenge|challenge-platform|are you a robot|verify you are human", re.I)
_HREF = re.compile(r"""href=["']([^"'#]+)["']""", re.I)


@dataclass
class Visit:
    url: str
    at: str
    status: int | None
    robots_allowed: bool


@dataclass
class Lookup:
    reason: str
    justification: str
    claim: str
    alternatives_tried: list[str]
    visits: list[Visit] = field(default_factory=list)
    document_url: str | None = None
    document_text: str | None = None
    # documento-obtenido | bloqueo-<status> | desafio | tope-de-paginas | sin-camino | error-red
    stopped: str = ""

    def as_payload(self) -> dict:
        """Lo que queda en la evidencia y en Metodologia: motivo, afirmacion y cada URL visitada."""
        return {
            "consulta_puntual": True,
            "motivo": self.reason,
            "justificacion": self.justification,
            "afirmacion": self.claim,
            "vias_alternativas": self.alternatives_tried,
            "visitas": [v.__dict__ for v in self.visits],
            "documento": self.document_url,
            "parada": self.stopped,
            "robots_excluia": any(not v.robots_allowed for v in self.visits),
        }


def _links(base: str, html: str) -> list[str]:
    host = urlsplit(base).netloc
    out: list[str] = []
    for href in _HREF.findall(html):
        url = urljoin(base, href)
        if urlsplit(url).netloc == host and url not in out:
            out.append(url)
    return out


async def lookup(
    start_url: str,
    *,
    is_document: Callable[[str, str], bool],
    reason: str,
    justification: str,
    claim: str,
    alternatives_tried: list[str],
    user_agent: str,
    next_hop: Callable[[list[str]], str | None] | None = None,
    max_pages: int = MAX_PAGES,
    delay: float = 1.0,
    transport: httpx.AsyncBaseTransport | None = None,
) -> Lookup:
    """Navega desde `start_url` hasta la primera pagina que `is_document(url, texto)` acepte.

    `next_hop` elige, entre los enlaces del mismo dominio de la pagina actual, el siguiente paso hacia el
    documento (None = no hay camino). Sin `next_hop` solo se consulta `start_url`.
    """
    if justification not in JUSTIFICATIONS:
        raise ValueError(f"justificacion debe ser una de {JUSTIFICATIONS}")
    if not reason.strip() or not claim.strip() or not alternatives_tried:
        raise ValueError("hacen falta motivo, afirmacion y las vias alternativas probadas")
    max_pages = min(max_pages, MAX_PAGES)
    rec = Lookup(reason, justification, claim, list(alternatives_tried))
    host = urlsplit(start_url).netloc
    robots = PoliteClient(user_agent, transport=transport)
    try:
        async with httpx.AsyncClient(
            headers={"User-Agent": user_agent}, timeout=20.0, follow_redirects=True, transport=transport
        ) as client:
            url: str | None = start_url
            while url:
                if len(rec.visits) >= max_pages:
                    rec.stopped = "tope-de-paginas"
                    break
                if urlsplit(url).netloc != host:
                    rec.stopped = "sin-camino"
                    break
                allowed = await robots.allowed(url)
                if rec.visits:
                    await asyncio.sleep(delay)
                at = datetime.now(UTC).isoformat(timespec="seconds")
                try:
                    resp = await client.get(url)
                except httpx.HTTPError:
                    rec.visits.append(Visit(url, at, None, allowed))
                    rec.stopped = "error-red"
                    break
                rec.visits.append(Visit(url, at, resp.status_code, allowed))
                if resp.status_code in BLOCKED:
                    rec.stopped = f"bloqueo-{resp.status_code}"
                    break
                text = resp.text
                if _CHALLENGE.search(text[:20000]):
                    rec.stopped = "desafio"
                    break
                if resp.status_code < 400 and is_document(url, text):
                    rec.document_url, rec.document_text = url, text
                    rec.stopped = "documento-obtenido"
                    break
                url = next_hop(_links(url, text)) if next_hop else None
                if url is None:
                    rec.stopped = "sin-camino"
    finally:
        await robots.aclose()
    return rec


def evidence_of(rec: Lookup, source: str, label: str, period: str | None = None, value: float | None = None):
    """La evidencia de la verificacion que motivo la consulta: el documento y la traza completa."""
    if rec.document_url is None:
        raise ValueError(f"la consulta no obtuvo el documento ({rec.stopped})")
    return Evidence(
        source=source, label=label, url=rec.document_url, period=period, value=value, payload=rec.as_payload()
    )
