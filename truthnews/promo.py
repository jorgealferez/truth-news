"""Detector de contenido publicitario de los medios: guias de compra, escaparates y ofertas.

Muchos medios publican en sus feeds piezas comerciales (enlaces de afiliado, "los mejores ... para tu
...", "por menos de 40 euros", chollos del dia) que no son noticias y no tienen nada que contrastar.
Se reconocen por la seccion de la URL o por el titular y el extracto; ninguna llega a la portada.
Determinista y sin dependencias: mismas reglas en el rastreo y en la limpieza de lo ya guardado.
"""

from __future__ import annotations

import re

from truthnews.classify import normalize

# Secciones comerciales de los medios espanoles (escaparate, compras, ofertas...): basta con la URL.
_URL_SECTION = re.compile(
    r"/(escaparate|compras|shopping|ofertas|chollos?|guia-de-compras?|guias-de-compra|mejores-precios|"
    r"el-recomendador|showroom|branded|patrocinad[oa]s?|publirreportaje|contenido-patrocinado|"
    r"brandcontent|brand-content|de-tiendas|comparador-financiero)(/|$|-)|/comprar/"
)
_SHOPS = (
    r"(amazon|aliexpress|el corte ingles|mediamarkt|pccomponentes|lidl|aldi|decathlon|primor|druni|"
    r"carrefour|zara|primark|ikea|leroy merlin)"
)
# Senales fuertes en titular o extracto (texto normalizado, sin tildes): una sola basta.
_STRONG = re.compile(
    r"\bpor menos de \d[\d.,]*\s?(euros?|eur|€)"
    r"|\b(chollazos?|chollos? del dia|ofertas? flash|ofertas? del dia|codigo (de )?descuento|"
    r"cupon(es)? (de )?descuento|precio minimo historico en)\b"
    r"|\b(ofertas?|chollos?|descuentos?|rebajas?) (del |de |en el |para el )?"
    r"(black friday|cyber monday|prime day|singles day)\b"
    r"|\b(contenido patrocinado|publirreportaje|en colaboracion con la marca|articulo patrocinado)\b"
    rf"|\ben {_SHOPS}\b.{{0,40}}\b(oferta|descuento|rebaja|chollo)"
    rf"|\b(oferta|descuento|rebaja|chollo)s?\b.{{0,40}}\ben {_SHOPS}\b"
)
# "Los mejores X para tu Y": guia de compra si se dirige al lector como consumidor o da precio o marca.
_BEST_OF = re.compile(r"^(los|las) (\d+ )?mejores \w+")
_BEST_OF_EDITORIAL = re.compile(
    r"^(los|las) (\d+ )?mejores (momentos|goles|jugadas|imagenes|fotos|fotografias|frases|memes|"
    r"jugadores|jugadoras|equipos|deportistas|estudiantes|alumnos|colegios|universidades|hospitales|"
    r"medicos|ciudades|paises|destinos|playas|pueblos|empresas|bancos|discos|canciones)\b"
)
_CONSUMER = re.compile(
    r"\b(tu|tus|te|para (regalar|el hogar|casa|tu)|que puedes comprar|comprar|baratos?|baratas?|"
    r"calidad[- ]precio|analisis y comparativa|comparativa|del mercado|segun (los )?usuarios)\b"
    r"|\d[\d.,]*\s?(euros?|€)"
)


def is_promotional(title: str, summary: str = "", url: str = "") -> bool:
    """La pieza es comercial (guia de compra, oferta, escaparate o contenido patrocinado)."""
    path = re.sub(r"^https?://[^/]+", "", normalize(url or ""))
    if _URL_SECTION.search(path):
        return True
    head = normalize(" ".join((title or "").split()))
    text = f"{head} {normalize(' '.join((summary or '').split()))[:400]}"
    if _STRONG.search(text):
        return True
    return bool(_BEST_OF.match(head) and not _BEST_OF_EDITORIAL.match(head) and _CONSUMER.search(text))
