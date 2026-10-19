"""Datos estructurados para buscadores (ADR 0038): JSON-LD de schema.org.

Cada funcion devuelve un dict listo para `jsonld()`, que lo serializa en un <script> seguro. Solo se
declara lo que la pagina muestra y con fechas reales; si falta el dato, el campo no se escribe.

- NewsMediaOrganization y WebSite: en todas las paginas (quien publica y con que principios).
- ClaimReview: en cada verificacion con veredicto ("sin datos" no lleva: no hay valoracion).
- NewsArticle: en hilos, piezas propias e investigaciones (contenido propio, elaborado con IA).
- BreadcrumbList: la misma miga de pan que se ve en la pagina.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime

from markupsafe import Markup

CONTEXT = "https://schema.org"
# Escala fija del veredicto (documentada en Metodologia y en el ADR 0038): 1 falso ... 4 verdadero.
RATING = {"falso": 1, "enganoso": 2, "impreciso": 3, "verdadero": 4}
BEST, WORST = 4, 1
LOGO = "/static/icon-512.png"


def _iso(value: datetime | None) -> str | None:
    if value is None:
        return None
    value = value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)
    return value.replace(microsecond=0).isoformat()


def _clean(obj):
    """Quita claves vacias (None, '', [], {}) para no declarar lo que no hay."""
    if isinstance(obj, dict):
        out = {k: _clean(v) for k, v in obj.items()}
        return {k: v for k, v in out.items() if v not in (None, "", [], {})}
    if isinstance(obj, list):
        return [_clean(v) for v in obj if v not in (None, "", [], {})]
    return obj


def jsonld(*objs: dict | None) -> Markup:
    """<script type="application/ld+json"> con uno o varios objetos; '</' se escapa (no cierra el script)."""
    items = [_clean(o) for o in objs if o]
    if not items:
        return Markup("")
    data = items[0] if len(items) == 1 else {"@context": CONTEXT, "@graph": items}
    if len(items) > 1:
        for item in data["@graph"]:
            item.pop("@context", None)
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return Markup(f'<script type="application/ld+json">{text}</script>')


def organization(site) -> dict:
    base = site.site_url
    return {
        "@context": CONTEXT,
        "@type": "NewsMediaOrganization",
        "@id": f"{base}/#organizacion",
        "name": site.site_name,
        "url": f"{base}/",
        "logo": {"@type": "ImageObject", "url": base + LOGO, "width": 512, "height": 512},
        "publishingPrinciples": f"{base}/metodologia",
        "verificationFactCheckingPolicy": f"{base}/metodologia",
        "correctionsPolicy": f"{base}/metodologia",
        "ownershipFundingInfo": f"{base}/acerca",
    }


def website(site, lang: str) -> dict:
    base = site.site_url
    return {
        "@context": CONTEXT,
        "@type": "WebSite",
        "@id": f"{base}/#web",
        "name": site.site_name,
        "url": f"{base}/",
        "inLanguage": lang,
        "publisher": {"@id": f"{base}/#organizacion"},
    }


def author(site) -> dict:
    """Autor de lo que elabora el propio medio: la redaccion automatizada y verificada."""
    return {
        "@type": "Organization",
        "name": f"Redacción {site.site_name} (IA, verificada)",
        "url": f"{site.site_url}/metodologia",
    }


def breadcrumbs(site, items: list[tuple[str, str | None]], here: str) -> dict | None:
    """`items`: (nombre, ruta) desde la portada; la ultima puede no tener ruta (es la pagina actual)."""
    if len(items) < 2:
        return None
    base = site.site_url
    return {
        "@context": CONTEXT,
        "@type": "BreadcrumbList",
        "itemListElement": [
            {"@type": "ListItem", "position": i, "name": name, "item": base + (path or here)}
            for i, (name, path) in enumerate(items, start=1)
        ],
    }


def claim_review(site, claim, verification, label: str, url: str, lang: str) -> dict | None:
    """ClaimReview de una verificacion; None si el veredicto no esta en la escala (p. ej. 'sin-datos')."""
    rating = RATING.get(verification.verdict)
    if rating is None:
        return None
    outlet = claim.outlet
    art = claim.article
    appearance = (
        {
            "@type": "NewsArticle",
            "url": art.url,
            "headline": art.title,
            "datePublished": _iso(art.published_at),
            "publisher": {"@type": "Organization", "name": outlet.name, "url": outlet.homepage},
        }
        if art is not None
        else None
    )
    return {
        "@context": CONTEXT,
        "@type": "ClaimReview",
        "url": url,
        "inLanguage": lang,
        "datePublished": _iso(verification.checked_at),
        "author": {
            "@id": f"{site.site_url}/#organizacion",
            "@type": "NewsMediaOrganization",
            "name": site.site_name,
        },
        "claimReviewed": claim.text,
        "itemReviewed": {
            "@type": "Claim",
            "author": {"@type": "Organization", "name": outlet.name, "url": outlet.homepage},
            "datePublished": _iso(art.published_at) if art is not None else None,
            "appearance": [appearance] if appearance else None,
        },
        # La cifra oficial con la que se juzga: el enlace a cada fuente citada.
        "citation": [
            {
                "@type": "Dataset",
                "name": " · ".join(x for x in (e.source, e.label, e.period) if x),
                "url": e.url,
            }
            for e in verification.evidence
            if e.url
        ],
        "reviewRating": {
            "@type": "Rating",
            "ratingValue": rating,
            "bestRating": BEST,
            "worstRating": WORST,
            "alternateName": label,
        },
    }


def news_article(
    site,
    *,
    url: str,
    headline: str,
    description: str | None,
    published: datetime | None,
    modified: datetime | None,
    lang: str,
    section: str | None = None,
    image: str | None = None,
) -> dict:
    """NewsArticle de contenido propio, con autor declarado y fechas reales."""
    base = site.site_url
    return {
        "@context": CONTEXT,
        "@type": "NewsArticle",
        "mainEntityOfPage": {"@type": "WebPage", "@id": url},
        "url": url,
        "headline": headline[:110],
        "description": description,
        "inLanguage": lang,
        "datePublished": _iso(published),
        "dateModified": _iso(modified or published),
        "articleSection": section,
        "image": [image or f"{base}/static/og-default.png"],
        "author": author(site),
        "publisher": {
            "@type": "NewsMediaOrganization",
            "@id": f"{base}/#organizacion",
            "name": site.site_name,
            "logo": {"@type": "ImageObject", "url": base + LOGO},
        },
        "isAccessibleForFree": True,
    }


def iso(value: datetime | None) -> str:
    """Para metas article:published_time; '' si no hay fecha."""
    return _iso(value) or ""


_SCRIPT = re.compile(r'<script type="application/ld\+json">(.*?)</script>', re.S)


def extract(html: str) -> list[dict]:
    """Los objetos JSON-LD de una pagina, aplanando @graph (para tests y comprobaciones en produccion)."""
    out: list[dict] = []
    for raw in _SCRIPT.findall(html):
        data = json.loads(raw)
        out += data.get("@graph", [data])
    return out


def of_type(html: str, kind: str) -> list[dict]:
    return [o for o in extract(html) if o.get("@type") == kind]
