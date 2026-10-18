"""Utilidades de texto: tokens normalizados, palabras vacias y raices aproximadas (es/en/pt/ca)."""

from __future__ import annotations

import re

from truthnews.classify import normalize

_STOPWORDS_TEXT = (
    "a al algo algunas algunos ante antes aqui asi aun aunque bajo bien cada casi como con contra "
    "cual cuales cuando de del desde donde dos e el ella ellas ello ellos en entre era eran es esa "
    "esas ese eso esos esta estan estas este esto estos fue fueron ha han hasta hay la las le les lo "
    "los mas me mi muy nada ni no nos nuestra nuestro o os otra otro otros para pero poco por porque "
    "que quien se sea segun ser si sido sin sobre son su sus tambien tan tanto te tiene tienen todo "
    "todos tras tu un una unas uno unos y ya yo hoy ayer manana ano anos dia dias mes meses tras sera "
    "seran puede pueden hace va van ver dice dicen cree ahora despues gran grandes nueva nuevo nuevas "
    "nuevos asi vez veces video videos directo ultima hora the of and to in for on with at by from as "
    "is are was were be been it its this that these those an or not but after over new says said will "
    "has have had more about into than who what when how why o os um uma na no nas nos da do das dos "
    "em por para com que se ao aos e "
)
STOPWORDS = frozenset(_STOPWORDS_TEXT.split())
_WORD = re.compile(r"[a-z0-9]+(?:[.,][0-9]+)?")


def stem(token: str) -> str:
    """Raiz aproximada por prefijo: robusta en espanol sin dependencias (vivienda/viviendas -> vivien)."""
    if token[0].isdigit():
        return token
    return token[:6]


def tokens(text: str) -> list[str]:
    out = []
    for tok in _WORD.findall(normalize(text)):
        if len(tok) < 3 and not tok[0].isdigit():
            continue
        if tok in STOPWORDS:
            continue
        out.append(stem(tok))
    return out
