"""Contratacion publica: anuncios del BOE (seccion V.A) y adjudicaciones de Espana publicadas en TED.

Fuentes, ambas de datos abiertos y permitidas por su robots.txt (medido 2026-10-19):

- BOE: sumario diario (`/datosabiertos/api/boe/sumario/AAAAMMDD`), seccion V.A "Contratacion del Sector
  Publico". Del titulo se leen el tipo de anuncio, el organo, el objeto y el expediente; si no se reconocen
  se dejan vacios, nunca se inventan.
- TED (Diario Oficial de la UE, suplemento S): API de busqueda anonima `api.ted.europa.eu/v3`. Avisos de
  adjudicacion (`can-standard`) con comprador en Espana: adjudicatario, NIF, importe y organo.

La Plataforma de Contratacion del Sector Publico excluye todo en su robots.txt (`Disallow: /`) y no se
rastrea (ADR 0003); solo cabe la consulta puntual de interes publico (ADR 0029).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

import httpx

from truthnews.data import client

BOE_BASE = "https://www.boe.es/datosabiertos/api/boe/sumario"
SECTION = "5A"  # V. Anuncios. - A. Contratacion del Sector Publico
TED_SEARCH = "https://api.ted.europa.eu/v3/notices/search"
TED_FIELDS = [
    "publication-number",
    "publication-date",
    "notice-title",
    "buyer-name",
    "winner-name",
    "winner-identifier",
    "result-value-notice",
    "total-value",
    "total-value-cur",
]
TED_PAGE = 250
TED_MAX_PAGES = 6

_KINDS = (
    ("formalizacion", re.compile(r"^anuncio de formalizaci[oó]n", re.I)),
    ("adjudicacion", re.compile(r"^anuncio de adjudicaci[oó]n", re.I)),
    ("licitacion", re.compile(r"^anuncio (?:previo )?de licitaci[oó]n", re.I)),
    ("anulacion", re.compile(r"^anuncio de (?:anulaci[oó]n|desistimiento|renuncia)", re.I)),
    ("rectificacion", re.compile(r"^anuncio de (?:rectificaci[oó]n|correcci[oó]n|modificaci[oó]n)", re.I)),
)
_ORGANO = re.compile(r"^anuncio[^:]*?\bde:\s*(.+?)\s+Objeto:", re.I)
_OBJETO = re.compile(r"\bObjeto:\s*(.+?)(?:\.\s+Expediente:|\.?$)", re.I | re.S)
_NIF = re.compile(r"^(?:[ABCDEFGHJNPQRSUVW]\d{7}[0-9A-J]|\d{8}[A-Z]|[XYZ]\d{7}[A-Z])$")
_EXPEDIENTE = re.compile(r"\bExpediente:\s*(.+?)\.?\s*$", re.I)


@dataclass
class Anuncio:
    id: str
    fecha: str
    tipo: str
    departamento: str
    organo: str
    objeto: str
    expediente: str
    titulo: str
    url: str


@dataclass
class Adjudicacion:
    id: str
    fecha: str
    comprador: str
    objeto: str
    url: str
    importe: float | None = None
    moneda: str = "EUR"
    adjudicatarios: list[tuple[str, str]] = field(default_factory=list)  # (nombre, NIF o "")


def _as_list(node) -> list:
    if isinstance(node, list):
        return node
    return [node] if node else []


def kind_of(titulo: str) -> str:
    for kind, rx in _KINDS:
        if rx.search(titulo):
            return kind
    return "otro"


def split_title(titulo: str) -> tuple[str, str, str]:
    """(organo, objeto, expediente) de 'Anuncio de ... de: <organo>. Objeto: <objeto>. Expediente: <exp>.'"""
    m = _ORGANO.search(titulo)
    # El punto que separa el organo del objeto se quita; el de una abreviatura ('O.A.') se queda.
    organo = m.group(1).strip() if m else ""
    if not re.search(r"(?:^|[\s.])\w\.$", organo):
        organo = re.sub(r"\s*\.$", "", organo)
    m = _OBJETO.search(titulo)
    objeto = m.group(1).strip().rstrip(".") if m else ""
    m = _EXPEDIENTE.search(titulo)
    expediente = m.group(1).strip() if m else ""
    return organo, objeto, expediente


def parse_boe(payload: dict, day: date) -> list[Anuncio]:
    """Anuncios de la seccion V.A de un sumario del BOE ya descargado."""
    out: list[Anuncio] = []
    sumario = (payload.get("data") or {}).get("sumario") or {}
    for diario in _as_list(sumario.get("diario")):
        for sec in _as_list(diario.get("seccion")):
            if sec.get("codigo") != SECTION:
                continue
            for dep in _as_list(sec.get("departamento")):
                items = _as_list(dep.get("item"))
                for ep in _as_list(dep.get("epigrafe")):
                    items += _as_list(ep.get("item"))
                for it in items:
                    titulo = (it.get("titulo") or "").strip()
                    if not titulo or not it.get("identificador"):
                        continue
                    url = it.get("url_html")
                    url = url if isinstance(url, str) else (it.get("url_pdf") or {}).get("texto", "")
                    organo, objeto, expediente = split_title(titulo)
                    out.append(
                        Anuncio(
                            id=it["identificador"],
                            fecha=day.isoformat(),
                            tipo=kind_of(titulo),
                            departamento=(dep.get("nombre") or "").strip(),
                            organo=organo,
                            objeto=objeto,
                            expediente=expediente,
                            titulo=titulo,
                            url=url,
                        )
                    )
    return out


def boe_anuncios(day: date, transport: httpx.BaseTransport | None = None) -> list[Anuncio]:
    """Anuncios de licitacion, adjudicacion y formalizacion publicados en el BOE de un dia."""
    with client(transport) as c:
        resp = c.get(f"{BOE_BASE}/{day:%Y%m%d}", headers={"Accept": "application/json"})
    if resp.status_code != 200:
        return []
    return parse_boe(resp.json(), day)


def _spa(node) -> list[str]:
    """Textos en castellano de un campo multilingue de TED (o en ingles si no los hay)."""
    if isinstance(node, dict):
        for key in ("spa", "eng"):
            if node.get(key):
                return [v for v in _as_list(node[key]) if isinstance(v, str)]
        return []
    return [v for v in _as_list(node) if isinstance(v, str)]


def _amount(raw) -> float | None:
    for v in _as_list(raw):
        try:
            return float(v)
        except (TypeError, ValueError):
            continue
    return None


def parse_ted(payload: dict) -> list[Adjudicacion]:
    out: list[Adjudicacion] = []
    for n in payload.get("notices") or []:
        pub = n.get("publication-number")
        if not pub:
            continue
        title = (_spa(n.get("notice-title")) or [""])[0]
        # 'España – <descripcion CPV> – <objeto>': se queda el objeto.
        parts = title.split(" – ", 2)
        objeto = parts[2] if len(parts) == 3 else title
        names = list(dict.fromkeys(x.strip() for x in _spa(n.get("winner-name")) if x.strip()))
        ids = _as_list(n.get("winner-identifier"))
        nifs = list(dict.fromkeys(v.strip() for v in ids if isinstance(v, str)))
        # TED no da los identificadores en el orden de los nombres (medido: aviso 692450-2026). El NIF solo
        # se atribuye con un unico adjudicatario y un unico identificador con forma de NIF espanol.
        nif = nifs[0] if len(names) == 1 and len(nifs) == 1 and _NIF.match(nifs[0]) else ""
        winners = [(name, nif if len(names) == 1 else "") for name in names]
        html = (n.get("links") or {}).get("html") or {}
        out.append(
            Adjudicacion(
                id=pub,
                fecha=str(n.get("publication-date") or "")[:10],
                comprador=(_spa(n.get("buyer-name")) or [""])[0].strip(),
                objeto=objeto.strip(),
                url=html.get("SPA") or f"https://ted.europa.eu/es/notice/-/detail/{pub}",
                importe=_amount(n.get("result-value-notice")) or _amount(n.get("total-value")),
                moneda=(_as_list(n.get("total-value-cur")) or ["EUR"])[0],
                adjudicatarios=winners,
            )
        )
    return out


def ted_query(since: date, until: date, country: str = "ESP") -> str:
    return (
        f"buyer-country={country} AND notice-type=can-standard"
        f" AND publication-date>={since:%Y%m%d} AND publication-date<={until:%Y%m%d}"
    )


def ted_adjudicaciones(
    since: date, until: date, transport: httpx.BaseTransport | None = None, max_pages: int = TED_MAX_PAGES
) -> list[Adjudicacion]:
    """Adjudicaciones con comprador en Espana publicadas en TED entre dos fechas (ambas incluidas)."""
    out: list[Adjudicacion] = []
    with client(transport) as c:
        for page in range(1, max_pages + 1):
            body = {"query": ted_query(since, until), "fields": TED_FIELDS, "limit": TED_PAGE, "page": page}
            resp = c.post(TED_SEARCH, json=body)
            if resp.status_code != 200:
                break
            data = resp.json()
            out += parse_ted(data)
            if page * TED_PAGE >= (data.get("totalNoticeCount") or 0):
                break
    return out
