"""Cumplimiento normativo UE y Espana (peticion del usuario 2026-10-19, ADR 0039).

`STORAGE` es el inventario de todo lo que el sitio guarda en el navegador del lector. La politica de
cookies se pinta desde aqui y `tests/test_legal.py` falla si el codigo escribe una cookie o una clave de
almacenamiento local que no este en la lista: anadir una exige declararla (y, si no es exenta segun la
LSSI art. 22.2, pedir consentimiento antes, que hoy no hace falta porque todo lo guardado es exento).
"""

from __future__ import annotations

from dataclasses import dataclass

from truthnews.config import Settings


@dataclass(frozen=True)
class Stored:
    name: str
    kind: str  # cookie | localStorage
    purpose: dict[str, str]
    duration: dict[str, str]
    # Por que no necesita consentimiento (LSSI art. 22.2 y Guia de cookies de la AEPD, 2023).
    exempt: dict[str, str]


STORAGE: tuple[Stored, ...] = (
    Stored(
        name="lang",
        kind="cookie",
        purpose={
            "es": "Recordar el idioma que eliges con el selector de idioma.",
            "en": "Remember the language you choose with the language selector.",
        },
        duration={"es": "1 año", "en": "1 year"},
        exempt={
            "es": "Personalización pedida por ti (preferencia de idioma): exenta de consentimiento.",
            "en": "Customisation you asked for (language preference): exempt from consent.",
        },
    ),
    Stored(
        name="zona",
        kind="cookie",
        purpose={
            "es": "Recordar la zona que eliges en el banner de Ridelta (a mano o con «usar mi ubicación») "
            "para enseñarte el sitio de tu provincia. Solo guarda el nombre de la zona; la ubicación se "
            "calcula en tu navegador y nunca se envía.",
            "en": "Remember the area you choose in the Ridelta banner (by hand or with “use my location”) "
            "to show you your province's site. It only stores the area name; your location is worked out in "
            "your browser and never sent.",
        },
        duration={"es": "1 año", "en": "1 year"},
        exempt={
            "es": "Personalización pedida por ti (preferencia de zona): exenta de consentimiento.",
            "en": "Customisation you asked for (area preference): exempt from consent.",
        },
    ),
    Stored(
        name="nm_last_visit",
        kind="localStorage",
        purpose={
            "es": "Marcar como «Nuevo» lo publicado desde tu última visita a la portada. Se queda en tu "
            "navegador y nunca se envía al servidor.",
            "en": "Mark as “New” what was published since your last visit to the home page. It stays in "
            "your browser and is never sent to the server.",
        },
        duration={"es": "Hasta que lo borres", "en": "Until you delete it"},
        exempt={
            "es": "Necesario para la función que usas y sin envío a nadie: exento de consentimiento.",
            "en": "Needed for the feature you use and never sent anywhere: exempt from consent.",
        },
    ),
)

# slug -> clave de titulo en i18n.yaml; el orden es el del pie.
PAGES: dict[str, str] = {
    "aviso-legal": "legal_notice",
    "privacidad": "privacy",
    "cookies": "cookies",
    "transparencia": "transparency",
}

OWNER_FIELDS = ("legal_owner", "legal_tax_id", "legal_address", "legal_email")


def missing_owner_data(settings: Settings) -> list[str]:
    """Datos obligatorios del titular que faltan (LSSI art. 10). Se muestran como pendientes."""
    return [f for f in OWNER_FIELDS if not getattr(settings, f).strip()]


def content_lang(lang: str) -> str:
    """Los textos legales estan en es y en; cualquier otro idioma lee la version inglesa."""
    return lang if lang in ("es", "en") else "en"
