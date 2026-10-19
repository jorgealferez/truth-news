"""Consulta puntual de interes publico (ADR 0023, precisa el 0003).

No es rastreo: una lista cerrada de URLs del mismo host (como mucho MAX_PAGES) para llegar a un documento
concreto que hace falta para contrastar una afirmacion concreta, solo con justificacion completa. Se
identifica con el User-Agent del proyecto, se para ante cualquier bloqueo tecnico y lo registra todo. El
rastreador no importa este modulo y nada de lo que se descarga aqui se reutiliza para seguir rastreando.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import httpx

MAX_PAGES = 5
CONDITIONS = ("dudas_entre_medios", "falta_pruebas_entidad")  # decision del usuario, 2026-10-19
BLOCKING = {401, 403, 407, 429, 451}
_CHALLENGE = ("captcha", "cf-chl", "challenge-platform", "are you a robot", "verifica que eres humano")


class NotJustified(ValueError):
    """Falta algo de la justificacion: la consulta no empieza."""


@dataclass(frozen=True)
class Justification:
    claim: str  # la afirmacion concreta que se verifica
    condition: str  # una de CONDITIONS
    reason: str  # por que este documento es imprescindible
    alternatives_tried: tuple[str, ...]  # vias que ya se intentaron sin exito

    def check(self) -> None:
        if not self.claim.strip() or not self.reason.strip():
            raise NotJustified("falta la afirmacion o el motivo")
        if self.condition not in CONDITIONS:
            raise NotJustified(f"condicion no admitida: {self.condition!r}")
        if not [a for a in self.alternatives_tried if a.strip()]:
            raise NotJustified("hay que intentar antes otra via")


@dataclass
class Visit:
    url: str
    status: int | None
    fetched_at: str
    robots_excluded: bool
    sha256: str | None = None
    note: str = ""


@dataclass
class Consultation:
    justification: Justification
    visits: list[Visit] = field(default_factory=list)
    outcome: str = "pendiente"  # obtenido | bloqueado | error
    document: str | None = None  # texto del documento objetivo, solo si se obtuvo

    def evidence_payload(self) -> dict:
        """Registro publico para `evidence.payload["consulta_puntual"]` (sin el documento)."""
        return {
            "motivo": self.justification.reason,
            "afirmacion": self.justification.claim,
            "condicion": self.justification.condition,
            "alternativas_intentadas": list(self.justification.alternatives_tried),
            "resultado": self.outcome,
            "urls": [asdict(v) for v in self.visits],
        }


def _robots_excluded(client: httpx.Client, url: str, user_agent: str) -> bool:
    """Solo para registrarlo: si robots.txt excluye la URL (la consulta puntual no lo aplica, lo declara)."""
    parts = urlsplit(url)
    try:
        resp = client.get(f"{parts.scheme}://{parts.netloc}/robots.txt")
    except httpx.HTTPError:
        return False
    if resp.status_code != 200:
        return resp.status_code >= 500
    parser = RobotFileParser()
    parser.parse(resp.text.splitlines())
    return not parser.can_fetch(user_agent, url)


def consult(
    urls: list[str],
    justification: Justification,
    user_agent: str,
    transport: httpx.BaseTransport | None = None,
    now=lambda: datetime.now(UTC),
) -> Consultation:
    """Recorre `urls` en orden (la ultima es el documento) y se para al obtenerlo o ante un bloqueo."""
    justification.check()
    if not urls or len(urls) > MAX_PAGES:
        raise NotJustified(f"entre 1 y {MAX_PAGES} paginas")
    host = urlsplit(urls[0]).netloc
    if any(urlsplit(u).netloc != host or urlsplit(u).scheme not in ("http", "https") for u in urls):
        raise NotJustified("todas las paginas tienen que ser del mismo host")
    out = Consultation(justification)
    # Cliente propio y efimero: nada se comparte con el rastreador.
    with httpx.Client(
        headers={"User-Agent": user_agent}, timeout=20, follow_redirects=False, transport=transport
    ) as client:
        excluded = _robots_excluded(client, urls[0], user_agent)
        for i, url in enumerate(urls):
            current, resp, hops = url, None, 0
            while True:  # redirecciones a mano: solo dentro del mismo host
                try:
                    resp = client.get(current)
                except httpx.HTTPError as exc:
                    out.visits.append(Visit(current, None, now().isoformat(), excluded, note=str(exc)[:200]))
                    out.outcome = "error"
                    return out
                location = resp.headers.get("location")
                if resp.is_redirect and location and hops < 3:
                    target = str(resp.url.join(location))
                    out.visits.append(
                        Visit(current, resp.status_code, now().isoformat(), excluded, note="redireccion")
                    )
                    if urlsplit(target).netloc != host:
                        out.outcome = "bloqueado"
                        out.visits[-1].note = f"redireccion a otro host ({urlsplit(target).netloc}): se para"
                        return out
                    current, hops = target, hops + 1
                    continue
                break
            body = resp.text
            visit = Visit(
                current,
                resp.status_code,
                now().isoformat(),
                excluded,
                hashlib.sha256(resp.content).hexdigest(),
            )
            out.visits.append(visit)
            if resp.status_code in BLOCKING or any(m in body.lower() for m in _CHALLENGE):
                visit.note = "bloqueo tecnico: se para sin rodearlo"
                out.outcome = "bloqueado"
                return out
            if resp.status_code >= 400:
                visit.note = "error del sitio"
                out.outcome = "error"
                return out
            if i == len(urls) - 1:
                out.document = body
                out.outcome = "obtenido"
    return out
