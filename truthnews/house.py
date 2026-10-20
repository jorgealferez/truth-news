"""Publicidad propia de Ridelta por zona: banners rotativos y contenido patrocinado (ADR 0055).

Rellena los huecos de publicidad que ads-service deja vacios (hoy todos: falta ADS_SITE_KEY) con banners de
una marca propia, y publica piezas de contenido patrocinado por zona en /patrocinado. Todo sale de
`registry/house_ads.yaml`: zonas, dominios y frases copiados de vtc-clm, sin tablas ni subasta.

La zona del lector se decide, por este orden:
  1. la que el lector eligio (cookie `zona`, de preferencia: la pone el propio lector desde el banner, a
     mano o con "usar mi ubicacion", que se resuelve en su navegador; la ubicacion nunca llega al servidor);
  2. el contenido de la pagina (municipios de una zona en el titular y los extractos, o la comunidad de la
     pagina o de sus medios);
  3. si no se sabe, el sitio generico (ridelta.com).

Cada banner y cada pieza se etiquetan como publicidad (LSSI art. 20, Ley 3/1991 art. 26) y sus enlaces van
con rel="sponsored": la publicidad nunca se hace pasar por informacion.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from functools import lru_cache
from urllib.parse import urlencode

from truthnews.classify import normalize
from truthnews.registry import REGISTRY_DIR, _load_yaml

COOKIE = "zona"
GENERIC = "ridelta"
SOURCE = "nosmienten"
# Municipios que tambien son apellidos o palabras comunes: no cuentan al leer el contenido de la pagina.
_TEXT_SKIP = frozenset(["toro", "consuegra", "torrijos", "huete", "bargas", "sonseca", "yeles", "borox"])
_SLUG = re.compile(r"^[a-z0-9-]{1,40}$")


@dataclass(frozen=True)
class Zone:
    slug: str
    name: str
    domain: str
    kind: str  # province | region | generic
    hub: str | None = None
    region: str | None = None
    capital: str = ""
    roads: str = ""
    headline: str = ""
    intro: str = ""
    demand: str = ""
    places: tuple[str, ...] = ()
    towns: tuple[tuple[str, float, float], ...] = ()
    provinces: tuple[str, ...] = ()

    @property
    def site(self) -> str:
        return f"https://{self.domain}"


@lru_cache(maxsize=1)
def config() -> dict:
    return _load_yaml(REGISTRY_DIR / "house_ads.yaml")


@lru_cache(maxsize=1)
def zones() -> dict[str, Zone]:
    """Todas las zonas por slug: provincias, comunidades y el generico."""
    cfg = config()
    out: dict[str, Zone] = {}
    for z in cfg["zones"]:
        out[z["slug"]] = Zone(
            slug=z["slug"],
            name=z["name"],
            domain=z["domain"],
            kind="province",
            hub=z["hub"],
            capital=z.get("capital", ""),
            roads=z.get("roads", ""),
            headline=z.get("headline", ""),
            intro=z.get("intro", ""),
            demand=z.get("demand", ""),
            places=tuple(z.get("places", ())),
            towns=tuple((t[0], float(t[1]), float(t[2])) for t in z.get("towns", ())),
        )
    for r in cfg["regions"]:
        out[r["slug"]] = Zone(
            slug=r["slug"],
            name=r["name"],
            domain=r["domain"],
            kind="region",
            region=r["region"],
            provinces=tuple(r["provinces"]),
        )
    out[GENERIC] = Zone(slug=GENERIC, name=cfg["brand"], domain=cfg["generic_domain"], kind="generic")
    return out


def brand() -> str:
    return config()["brand"]


def provinces() -> list[Zone]:
    return [z for z in zones().values() if z.kind == "province"]


def regions() -> list[Zone]:
    return [z for z in zones().values() if z.kind == "region"]


def hub_of(zone: Zone) -> Zone | None:
    return zones().get(zone.hub) if zone.hub else None


def province_zones(region: Zone) -> list[Zone]:
    return [zones()[p] for p in region.provinces if p in zones()]


def chosen(raw: str | None) -> Zone | None:
    """La zona que el lector eligio (cookie), si es una zona conocida."""
    if not raw or not _SLUG.match(raw):
        return None
    return zones().get(raw)


@lru_cache(maxsize=1)
def _town_index() -> list[tuple[re.Pattern, str]]:
    index = []
    for z in provinces():
        for name, _lat, _lon in z.towns:
            key = normalize(name)
            if key in _TEXT_SKIP or len(key) < 4:
                continue
            index.append((re.compile(r"(?<!\w)" + re.escape(key) + r"(?!\w)"), z.slug))
    return index


def from_content(texts: Iterable[str], region_codes: Iterable[str | None] = ()) -> Zone | None:
    """Zona por el contenido: la provincia con mas municipios citados; si no, la comunidad de la pagina."""
    text = normalize(" ".join(t for t in texts if t))
    hits: Counter[str] = Counter()
    for pattern, slug in _town_index():
        hits[slug] += len(pattern.findall(text))
    hits = Counter({k: v for k, v in hits.items() if v})
    if hits:
        return zones()[hits.most_common(1)[0][0]]
    codes = Counter(c.upper() for c in region_codes if c)
    for code, _n in codes.most_common():
        for r in regions():
            if r.region == code:
                return r
    return None


def _km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(a))


def nearest(lat: float, lon: float) -> Zone | None:
    """Zona del municipio mas cercano dentro del radio; None si el punto queda fuera de todas.

    Es la misma cuenta que hace `static/house.js` en el navegador: aqui sirve para las pruebas y para quien
    llega a /zona con coordenadas (sin JavaScript no se pide la ubicacion).
    """
    best, best_km = None, float(config()["radius_km"])
    for z in provinces():
        for _name, tlat, tlon in z.towns:
            d = _km(lat, lon, tlat, tlon)
            if d <= best_km:
                best, best_km = z, d
    return best


def resolve(
    cookie: str | None, texts: Iterable[str], region_codes: Iterable[str | None] = ()
) -> tuple[Zone, str]:
    """(zona, por que): eleccion del lector, contenido de la pagina o generico."""
    if z := chosen(cookie):
        return z, "chosen"
    if z := from_content(texts, region_codes):
        return z, "content"
    return zones()[GENERIC], "generic"


def link(url: str, zone: Zone, medium: str, content: str) -> str:
    """Enlace de salida con UTM para medir en el destino lo que llega desde nosmienten.com."""
    q = urlencode(
        {
            "utm_source": SOURCE,
            "utm_medium": medium,
            "utm_campaign": f"ridelta-{zone.slug}",
            "utm_content": content,
        }
    )
    return f"{url}{'&' if '?' in url else '?'}{q}"


def _apps_line(lang: str) -> tuple[str, str]:
    if config().get("apps_in_stores"):
        return (
            ("Ridelta en iOS y Android", "La misma cuenta y el mismo precio en la app y en la web.")
            if lang == "es"
            else ("Ridelta on iOS and Android", "The same account and price in the app and on the web.")
        )
    return (
        ("Ridelta en tu móvil", "La web se instala como app: misma cuenta, mismo precio y tus reservas.")
        if lang == "es"
        else (
            "Ridelta on your phone",
            "Install the website as an app: same account, same price, your bookings.",
        )
    )


def big_platform() -> dict:
    """La gran plataforma de referencia y su lista de ciudades (registro), para decir donde no llega."""
    return config()["big_platform"]


def outside_big(zone: Zone) -> bool:
    """Ningun municipio de la zona esta en la lista de ciudades de la gran plataforma."""
    cities = {normalize(c) for c in big_platform()["cities"]}
    names = [t[0] for t in zone.towns] if zone.kind == "province" else []
    for p in province_zones(zone) if zone.kind == "region" else []:
        names += [t[0] for t in p.towns]
    return bool(names) and not any(normalize(n) in cities for n in names)


def small_towns(zone: Zone, n: int = 5) -> list[str]:
    """Los municipios de la zona que no son cabecera: los ultimos de su lista de origenes (vtc-clm)."""
    names = [t[0] for t in zone.towns]
    return names[3:][-n:] if len(names) > 3 else names


def creatives(zone: Zone, lang: str = "es") -> list[dict]:
    """Los banners de una zona, en orden de rotacion. Solo afirman lo que hace el servicio (ADR 0055)."""
    es = lang == "es"
    b = brand()
    apps_head, apps_body = _apps_line(lang)
    generic = zones()[GENERIC]
    if zone.kind == "province":
        towns = ", ".join(t[0] for t in zone.towns[:3])
        rows = [
            (
                "precio",
                f"{zone.name}: traslados con precio cerrado antes de salir"
                if es
                else f"{zone.name}: fixed-price rides",
                zone.intro
                if es
                else "Airport, high-speed rail and Madrid, with the price fixed before you leave.",
                "Ver mi precio" if es else "See my price",
                f"{zone.site}/pedir",
            ),
            (
                "zona",
                (f"Desde {towns} y toda la provincia" if es else f"From {towns} and the whole province"),
                (
                    f"La web de {b} para {zone.name}: municipios, rutas y precios de la provincia."
                    if es
                    else f"A {b} site for {zone.name}, with its towns, routes and prices."
                ),
                "Ver la web de la zona" if es else "Open the local site",
                zone.site,
            ),
            (
                "pueblos",
                (
                    "Donde no llegan las grandes plataformas, llegamos"
                    if es
                    else "Where the big platforms do not go, we do"
                ),
                (
                    f"También desde {_list(small_towns(zone, 3))}, con precio cerrado antes de salir."
                    if es
                    else f"Also from {', '.join(small_towns(zone, 3))}, with a fixed price before you leave."
                ),
                "Ver mi precio" if es else "See my price",
                f"{zone.site}/pedir",
            ),
            (
                "licencia",
                "Conductores con licencia propia y vehículo confirmado"
                if es
                else "Licensed drivers, confirmed vehicle",
                (
                    "Cada traslado lo presta un profesional con su licencia o autorización en regla. "
                    f"{zone.domain}"
                    if es
                    else f"Every ride is provided by a professional with a valid licence. {zone.domain}"
                ),
                "Reservar" if es else "Book",
                f"{zone.site}/pedir",
            ),
            (
                "app",
                apps_head,
                apps_body,
                "Cómo instalarla" if es else "How to install",
                f"{generic.site}/apps",
            ),
        ]
    elif zone.kind == "region":
        names = ", ".join(p.name for p in province_zones(zone))
        rows = [
            (
                "provincias",
                f"{b} en {zone.name}: una web para cada provincia"
                if es
                else f"{b} in {zone.name}: one site per province",
                (
                    f"{names}. Elige la tuya y reserva con precio cerrado."
                    if es
                    else f"{names}. Pick yours and book."
                ),
                "Elegir provincia" if es else "Choose province",
                zone.site,
            ),
            (
                "precio",
                "El precio se cierra antes de salir" if es else "The price is fixed before you leave",
                "Con IVA, desglosado y sin sorpresas por el tráfico."
                if es
                else "VAT included, itemised, no traffic surprises.",
                "Ver mi precio" if es else "See my price",
                zone.site,
            ),
            (
                "app",
                apps_head,
                apps_body,
                "Cómo instalarla" if es else "How to install",
                f"{generic.site}/apps",
            ),
        ]
    else:
        rows = [
            (
                "marca",
                f"{b}: traslados con precio cerrado" if es else f"{b}: fixed-price rides",
                (
                    "Una marca, una cuenta y un sitio propio para cada zona donde operamos."
                    if es
                    else "One brand, one account and a local site for every area we serve."
                ),
                "Dónde operamos" if es else "Where we operate",
                f"{generic.site}/cobertura",
            ),
            (
                "precio",
                "Ves el precio antes de reservar" if es else "See the price before you book",
                "Si no te encaja, no reservas y no cuesta nada."
                if es
                else "If it does not suit you, it costs nothing.",
                "Pedir un coche" if es else "Book a ride",
                f"{generic.site}/pedir",
            ),
            (
                "app",
                apps_head,
                apps_body,
                "Cómo instalarla" if es else "How to install",
                f"{generic.site}/apps",
            ),
        ]
    return [
        {
            "key": key,
            "headline": head,
            "body": body,
            "cta": cta,
            "url": link(url, zone, "banner", key),
            "display_url": zone.domain if key != "app" else generic.domain,
        }
        for key, head, body, cta, url in rows
    ]


def banner(zone: Zone, why: str, lang: str = "es") -> dict:
    """Hueco de publicidad propia, con la misma forma que pinta `_ad.html` (ad.house = True)."""
    return {
        "house": True,
        "format": "strip",
        "label": "Publicidad" if lang == "es" else "Advertising",
        "zone": zone.slug,
        "zone_name": zone.name,
        "why_key": f"house_why_{why}",
        "creatives": creatives(zone, lang),
        "advertiser": {"kind": "own", "name": brand(), "group_disclosure": ""},
    }


def teaser(zone: Zone, lang: str = "es") -> dict:
    """Hueco de listado: enlace a la pieza patrocinada de la zona (etiquetada igual que un anuncio)."""
    art = articles_for(zone)[0]
    return {
        "house": True,
        "teaser": True,
        "format": "native",
        "label": "Contenido patrocinado" if lang == "es" else "Sponsored content",
        "zone": zone.slug,
        "zone_name": zone.name,
        "why_key": "house_why_teaser",
        "headline": art["title"],
        "body": art["dek"],
        "url": f"/patrocinado/{art['slug']}",
        "advertiser": {"kind": "own", "name": brand(), "group_disclosure": ""},
    }


def fill(slots: Iterable[str], served: dict, zone: Zone, why: str, lang: str = "es") -> dict:
    """Los huecos pedidos que ads-service no lleno, con publicidad propia. Lo de ads-service va primero."""
    out = dict(served)
    for slot in slots:
        if slot in out:
            continue
        out[slot] = teaser(zone, lang) if slot == "list-native" else banner(zone, why, lang)
    return out


# --- Contenido patrocinado -------------------------------------------------------------------------------
# Piezas escritas con plantilla y los datos de la zona: cada frase dice algo que el servicio hace (vtc-clm)
# o que sale de su registro de zonas. Sin cifras de precio inventadas, sin promesas de disponibilidad.


def _list(items: Iterable[str]) -> str:
    items = list(items)
    if len(items) <= 1:
        return "".join(items)
    return ", ".join(items[:-1]) + " y " + items[-1]


def _province_articles(z: Zone) -> list[dict]:
    b = brand()
    big = big_platform()
    hub = hub_of(z)
    towns = [t[0] for t in z.towns]
    generic = zones()[GENERIC]
    apps = (
        f"Quien prefiere el móvil tiene las apps de {b} para iOS y Android, con la misma cuenta y el mismo "
        "precio."
        if config().get("apps_in_stores")
        else (
            f"Las apps de {b} para iOS y Android están en preparación para las tiendas; mientras tanto, la "
            "web se instala en el móvil como una app («Añadir a pantalla de inicio» en iPhone, «Instalar "
            "aplicación» en Android) y hace lo mismo."
        )
    )
    how = {
        "slug": f"como-funciona-ridelta-en-{z.slug}",
        "zone": z.slug,
        "title": f"Cómo funciona {b} en {z.name}: el precio del traslado, cerrado antes de salir",
        "dek": f"{z.domain} reúne los municipios, las rutas y los precios de la provincia; esto es lo que "
        "pasa desde que escribes el destino hasta que llega el coche.",
        "sections": [
            (
                "",
                [
                    f"{z.headline}. Así se presenta {z.domain}, la web de {b} para la provincia de {z.name}: "
                    f"{z.intro[0].lower()}{z.intro[1:]}",
                    z.demand,
                ],
            ),
            (
                "Tres pasos",
                [
                    "Primero se escribe de dónde a dónde. El buscador reconoce direcciones, aeropuertos, "
                    "estaciones y hospitales de las zonas donde opera el servicio.",
                    "Después se ve el precio, desglosado y con IVA, antes de reservar. Si no encaja, no se "
                    "reserva y no cuesta nada. Una vez confirmado, el importe no cambia por el tráfico, por "
                    "esperas razonables ni por la hora de salida.",
                    "Por último llega la confirmación con los datos del conductor y el seguimiento del "
                    "viaje. Se puede pagar con tarjeta en la web, a bordo o con factura de empresa.",
                ],
            ),
            (
                "Quién conduce",
                [
                    "Cada traslado lo presta un colaborador de taxi o VTC con su propia licencia o "
                    "autorización en vigor, con su vehículo y su seguro comprobados antes de recibir el "
                    f"primer servicio. {b} contrata el servicio, cierra el precio y asigna quién lo presta.",
                ],
            ),
            (
                f"Desde dónde se sale en {z.name}",
                [
                    f"La web de la provincia tiene página propia para {_list(towns[:8])}"
                    + (
                        f", entre otros municipios. Las carreteras de referencia son la {z.roads}."
                        if z.roads
                        else "."
                    ),
                    "Además de Barajas, Madrid y las estaciones de AVE, aparecen como destinos "
                    f"{_list(z.places[:6])}."
                    if z.places
                    else "",
                ],
            ),
            (
                "Donde no llegan las grandes",
                [
                    f"{big['name']} no tiene {z.name} en su lista de ciudades de España, según "
                    f"{big['source']}; y "
                    f"ninguno de los {len(towns)} municipios de origen de {z.domain} aparece en ella. {b} sí "
                    f"sale desde aquí: también desde {_list(small_towns(z))}, con el mismo precio cerrado "
                    "antes de salir y conductores con licencia, igual que en la capital de la provincia.",
                    "La siguiente zona se abre igual que esta: con taxistas, VTC y flotas que ya trabajan "
                    f"en ella. Si conduces o tienes flota donde {b} todavía no está, la puerta es "
                    f"{generic.domain}.",
                ]
                if outside_big(z)
                else [],
            ),
            ("En el móvil", [apps]),
            (
                "Dónde se reserva",
                [
                    f"En {z.domain}, la web de la provincia"
                    + (f"; en {hub.domain} están todas las de {hub.name}" if hub else "")
                    + f", y en {generic.domain}, el índice de todas las zonas donde opera {b}.",
                ],
            ),
        ],
        "links": [(z.domain, f"{z.site}/pedir"), (z.domain, z.site)]
        + ([(hub.domain, hub.site)] if hub else [])
        + [(f"{generic.domain}/apps", f"{generic.site}/apps")],
    }
    origin = towns[0] if towns else z.capital
    route = {
        "slug": f"traslado-barajas-ave-desde-{z.slug}",
        "zone": z.slug,
        "title": f"De {origin} a Barajas o al AVE sin calcular de cabeza: lo que hay que saber antes de "
        "reservar",
        "dek": f"Aeropuerto, estación o consulta en Madrid: cómo se pide en {z.name} un traslado con precio "
        "cerrado, qué datos pide la reserva y qué pasa si el vuelo se retrasa.",
        "sections": [
            ("", [z.demand]),
            (
                "Qué pide la reserva",
                [
                    "La dirección de recogida y la de destino, la hora y el número de pasajeros. En los "
                    "traslados de aeropuerto se puede añadir el número de vuelo o de tren, sillitas y "
                    "paradas intermedias.",
                    "Con el número de vuelo, el seguimiento muestra el estado del vuelo en vivo: la hora de "
                    "recogida a la llegada la marca el avión.",
                ],
            ),
            (
                "El precio",
                [
                    "Se calcula en el servidor con el trayecto concreto y se enseña desglosado antes de "
                    "confirmar. Es el que se paga: no se recalcula con el tráfico ni con esperas razonables.",
                    "Quien llama por teléfono puede recibir el presupuesto por WhatsApp y confirmarlo con "
                    "un toque al precio que se le dijo.",
                ],
            ),
            (
                "Para empresas",
                [
                    "Las cuentas de empresa y autónomos tienen factura completa, centros de coste por "
                    "servicio y personas autorizadas a pedir traslados con su tope.",
                ],
            ),
            (
                "Dónde se pide",
                [
                    f"En {z.domain}/pedir, con el mapa, el precio y el tiempo de llegada; o en {z.domain}, "
                    f"donde están las rutas de {_list(towns[:5])}."
                ],
            ),
        ],
        "links": [(f"{z.domain}/pedir", f"{z.site}/pedir"), (z.domain, z.site)],
    }
    return [how, route]


def _region_article(r: Zone) -> dict:
    b = brand()
    provs = province_zones(r)
    return {
        "slug": f"ridelta-en-{r.slug}",
        "zone": r.slug,
        "title": f"{b} en {r.name}: una web por provincia y el mismo precio cerrado en todas",
        "dek": f"{len(provs)} provincias, {len(provs)} dominios propios y un índice en {r.domain}: cómo está "
        f"organizado el servicio en {r.name}.",
        "sections": [
            (
                "",
                [
                    f"Quien busca un traslado en {r.name} no aterriza en una página genérica: cada provincia "
                    "tiene su propio sitio, con sus municipios, sus rutas y sus precios.",
                ],
            ),
            ("Las webs de cada provincia", [f"{p.name}: {p.domain}. {p.headline}." for p in provs]),
            (
                "Lo que es igual en todas",
                [
                    "El precio se cierra antes de salir, con IVA y desglosado; el vehículo va confirmado y "
                    "conduce un profesional con su licencia o autorización en regla. La misma cuenta sirve "
                    "en todas las provincias, en la web y en el móvil.",
                ],
            ),
        ],
        "links": [(r.domain, r.site)] + [(p.domain, p.site) for p in provs],
    }


def _generic_article() -> dict:
    b = brand()
    g = zones()[GENERIC]
    regs = regions()
    return {
        "slug": "como-funciona-ridelta",
        "zone": GENERIC,
        "title": f"Cómo funciona {b}: una marca, una cuenta y un sitio para cada zona",
        "dek": f"{g.domain} es la puerta de entrada; debajo, una web por comunidad y por provincia con los "
        "precios de cada trayecto.",
        "sections": [
            (
                "",
                [
                    f"{b} contrata traslados de viajeros en vehículo con conductor bajo contratación previa. "
                    "El transporte lo prestan colaboradores de taxi y VTC, cada uno con su licencia o "
                    "autorización, su seguro y su vehículo.",
                ],
            ),
            (
                "Dónde opera",
                [f"{r.name}: {r.domain}, con {_list([p.domain for p in province_zones(r)])}." for r in regs],
            ),
            (
                "Por qué una web por zona",
                [
                    "Porque quien busca un traslado en Albacete no quiere una página de Toledo: cada sitio "
                    "local tiene sus municipios, sus rutas y sus precios, y "
                    f"{g.domain} enlaza a todos ellos.",
                ],
            ),
        ],
        "links": [(g.domain, g.site), (f"{g.domain}/cobertura", f"{g.site}/cobertura")]
        + [(r.domain, r.site) for r in regs],
    }


def _rural_article() -> dict:
    """La pieza de cabecera: la apuesta por las zonas donde no operan las grandes plataformas."""
    b = brand()
    big = big_platform()
    g = zones()[GENERIC]
    provs = [p for p in provinces() if outside_big(p)]
    n_towns = sum(len(p.towns) for p in provs)
    regs = regions()
    return {
        "slug": "donde-no-llegan-las-grandes",
        "zone": GENERIC,
        "title": f"Donde no llegan las grandes: {b} apuesta por las provincias y los pueblos que las "
        "plataformas de ciudad dejan fuera",
        "dek": f"{len(provs)} provincias y {n_towns} municipios de origen en {_list(r.name for r in regs)}, "
        f"ninguno en la lista de ciudades de {big['name']}: así funciona un servicio de traslados pensado "
        "para quien vive lejos de las grandes capitales.",
        "sections": [
            (
                "",
                [
                    f"Las grandes plataformas de transporte con conductor eligen ciudades: {big['name']} "
                    f"nombra {len(big['cities'])} en España, de {_list(big['cities'][:4])} a "
                    f"{big['cities'][-1]}, según {big['source']}. {b} ha hecho el camino contrario: "
                    "empezar por las provincias que no están en esas listas.",
                    f"Hoy son {len(provs)}: {_list([p.name for p in provs])}. Ninguna de sus capitales ni de "
                    f"sus {n_towns} municipios de origen aparece en la lista de {big['name']}.",
                ],
            ),
            (
                "Lo que cambia para quien vive en un pueblo",
                [
                    "Ir a Barajas, a la estación de AVE o a una consulta en Madrid desde un pueblo suele "
                    "depender de que alguien te lleve. Con un traslado de precio cerrado se sabe lo que "
                    "cuesta antes de salir, con IVA y desglosado, y no cambia por el tráfico ni por esperas "
                    "razonables.",
                    "Cada traslado lo presta un taxista o VTC con su propia licencia o autorización, su "
                    "seguro y su vehículo, comprobados antes de recibir el primer servicio.",
                ]
                + [
                    f"En {p.name}, por ejemplo, se sale también desde {_list(small_towns(p, 4))}."
                    for p in provs[:: max(1, len(provs) // 4)][:4]
                ],
            ),
            (
                "Una web para cada provincia",
                [f"{p.name}: {p.domain}." for p in provs],
            ),
            (
                "Así se abre la siguiente",
                [
                    "Con taxistas, VTC y flotas que ya trabajan en la zona. Si conduces o tienes flota "
                    f"donde {b} todavía no está, el contacto está en {g.domain}.",
                ],
            ),
        ],
        "links": [(f"{g.domain}/cobertura", f"{g.site}/cobertura")] + [(p.domain, p.site) for p in provs],
    }


@lru_cache(maxsize=1)
def articles() -> list[dict]:
    """Todas las piezas patrocinadas: la de cabecera (sin grandes plataformas) y la generica primero."""
    out = [_rural_article(), _generic_article()]
    for r in regions():
        out.append(_region_article(r))
    for z in provinces():
        out.extend(_province_articles(z))
    return out


def article(slug: str) -> dict | None:
    return next((a for a in articles() if a["slug"] == slug), None)


def articles_for(zone: Zone) -> list[dict]:
    """Piezas de una zona (las de su comunidad y la generica detras); nunca vacio."""
    mine = [a for a in articles() if a["zone"] == zone.slug]
    hub = hub_of(zone)
    if hub:
        mine += [a for a in articles() if a["zone"] == hub.slug]
    return mine + [a for a in articles() if a["zone"] == GENERIC and a not in mine]


def zone_choices() -> list[dict]:
    """Para el selector del banner y para house.js: slug, nombre y municipios con coordenadas."""
    return [
        {"slug": z.slug, "name": z.name, "towns": [[n, la, lo] for n, la, lo in z.towns]} for z in provinces()
    ]
