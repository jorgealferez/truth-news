"""URLs legibles: `/tema/19-mas-electricos-por-debajo-de-25000-euros`.

El numero manda (resuelve la pagina); el slug es para lectores y buscadores. Cualquier otra forma
(`/tema/19`, un slug viejo tras cambiar el titular) redirige con 301 a la canonica.
"""

import re
import unicodedata

MAX_SLUG = 70
_THOUSANDS = re.compile(r"(?<=\d)[.,](?=\d{3}\b)")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def slugify(text: str | None, max_len: int = MAX_SLUG) -> str:
    """'Más eléctricos por debajo de 25.000 euros' -> 'mas-electricos-por-debajo-de-25000-euros'."""
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = _THOUSANDS.sub("", text.lower())
    slug = _NON_WORD.sub("-", text).strip("-")
    if len(slug) > max_len:
        slug = slug[: max_len + 1].rsplit("-", 1)[0]  # corta en palabra entera
    return slug


def path(kind: str, ident: int, title: str | None = None) -> str:
    """Ruta canonica de una pagina de detalle: /<kind>/<id>-<slug> (sin slug si no hay titulo)."""
    slug = slugify(title)
    return f"/{kind}/{ident}-{slug}" if slug else f"/{kind}/{ident}"


def parse_ref(ref: str) -> int | None:
    """'19-mas-electricos' o '19' -> 19; cualquier otra cosa -> None."""
    head = ref.split("-", 1)[0]
    return int(head) if head.isdigit() else None
