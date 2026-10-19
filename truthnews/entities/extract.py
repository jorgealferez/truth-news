"""Extraccion de personas, partidos, instituciones, organizaciones y lugares de un texto (ADR 0027/0028).

Dos vias, de mas a menos segura:

1. Registro curado (`registry/entities.yaml`): nombre y alias conocidos. Un alias en mayusculas ("PP",
   "INE") solo cuenta escrito en mayusculas; uno con inicial mayuscula ("Sumar", "Podemos") solo con
   ella, para no confundirlo con el verbo.
2. Descubrimiento: secuencias de nombres propios que empiezan por un nombre de pila (persona) o por la
   palabra de cabeza de una institucion u organizacion ("Tribunal Superior de Justicia de Madrid").
   Lo que no encaja en ninguna de las dos formas no se extrae: mejor callar que inventar una entidad.

Quien habla: una entidad "dice" una frase si en ella va precedida de "segun"/"en palabras de" o seguida
(con un inciso entre comas como mucho) de un verbo de declaracion. Sin eso, solo se la menciona.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from functools import lru_cache

import yaml

from truthnews.registry import REGISTRY_DIR

SPEAKER_KINDS = ("persona", "partido", "institucion", "organizacion")
QUOTE_MAX = 300
TEXT_MAX = 8000  # el texto largo no aporta entidades nuevas en proporcion a lo que cuesta

_SENTENCE = re.compile(r"(?<=[.!?;])\s+|\n+")
_UP = "A-ZÁÉÍÓÚÑÜÇÀÈÒÏ"
_LOW = "a-záéíóúñüçàèòï"
_TOKEN = rf"[{_UP}][{_LOW}]+(?:-[{_UP}][{_LOW}]+)?"
_CONNECTOR = (
    r"(?:de|del|de la|de las|de los|la|von|van|der|da|dos|i|y|por|por el|por la|para|para el|para la"
    r"|contra|contra el|contra la)"
)
_ORG_ONLY = re.compile(r"\s+(?:por|para|contra)\b.*$")
_PROPER = re.compile(rf"{_TOKEN}(?:\s+(?:{_CONNECTOR}\s+)?{_TOKEN}){{1,4}}")
_ROMAN = re.compile(r"\s+(?:I{1,3}|IV|V|VI{1,3}|IX|X|XI{1,3}|XIV|XV|XVI)\b")
# Palabras con mayuscula que no forman parte de un nombre (inicio de frase, dias, meses...).
_NOT_NAME = {
    "el",
    "la",
    "los",
    "las",
    "un",
    "una",
    "este",
    "esta",
    "estos",
    "estas",
    "ese",
    "esa",
    "aquel",
    "segun",
    "tras",
    "ante",
    "para",
    "por",
    "con",
    "sin",
    "sobre",
    "desde",
    "hasta",
    "durante",
    "pero",
    "aunque",
    "lunes",
    "martes",
    "miercoles",
    "jueves",
    "viernes",
    "sabado",
    "domingo",
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
    "the",
    "in",
    "on",
    "at",
    "mr",
    "mrs",
    "ms",
    "sr",
    "sra",
    "don",
    "dona",
    "presidente",
    "presidenta",
    "ministro",
    "ministra",
    "lider",
    "portavoz",
    "secretario",
    "secretaria",
    "alcalde",
    "alcaldesa",
    "rey",
    "reina",
}
_VERBS_AFTER = (
    r"(?:ha\s+|habia\s+|han\s+|has\s+|had\s+)?(?:dicho|dijo|dice|afirmado|afirmo|afirma|asegurado|aseguro"
    r"|asegura|declarado|declaro|declara|senalado|senalo|senala|explicado|explico|explica|denunciado"
    r"|denuncio|denuncia|defendido|defendio|defiende|criticado|critico|critica|advertido|advirtio|advierte"
    r"|anunciado|anuncio|anuncia|reconocido|reconocio|reconoce|insistido|insistio|insiste|sostenido"
    r"|sostuvo|sostiene|subrayado|subrayo|subraya|recordado|recordo|recuerda|cifrado|cifro|cifra|admitido"
    r"|admitio|admite|replicado|replico|replica|anadido|anadio|anade|apuntado|apunto|apunta|indicado|indico"
    r"|indica|manifestado|manifesto|respondido|respondio|lamentado|lamento|lamenta|acusado|acuso|acusa"
    r"|alertado|alerto|alerta|aclarado|aclaro|destacado|destaco|destaca|garantizado|garantizo|garantiza|said|says|told|stated|claimed|warned|announced|argued)"
)
_SPEAKS_AFTER = re.compile(rf"^(?P<inciso>\s*,[^,]{{1,80}},)?\s*,?\s*{_VERBS_AFTER}\b")
# "segun el ministro de Economia, X" admite palabras en medio; "ha dicho X" solo un articulo.
_SPEAKS_BEFORE = re.compile(
    r"(?:(?:\bsegun|\ben palabras de|\baccording to)\s+(?:[\w-]+,?\s+){0,5}"
    r"|\b(?:ha\s+(?:dicho|afirmado|asegurado|declarado|senalado|explicado)|dijo|afirmo|aseguro|declaro"
    r"|explico|senalo)\s+(?:(?:el|la|los|las)\s+)?)$"
)


def fold(text: str) -> str:
    """Minusculas sin tildes con la misma longitud que el original (los indices siguen valiendo)."""
    out = []
    for ch in text:
        base = unicodedata.normalize("NFKD", ch.lower())
        base = "".join(c for c in base if not unicodedata.combining(c))
        out.append(base[0] if base else ch)
    return "".join(out)


@dataclass(frozen=True)
class Known:
    key: str
    name: str
    kind: str
    country: str | None
    aliases: tuple[str, ...]


@dataclass
class Found:
    key: str
    name: str
    kind: str
    country: str | None = None
    curated: bool = False
    count: int = 0
    speaks: bool = False
    quote: str | None = None
    spans: list[tuple[int, int]] = field(default_factory=list)


def entity_key(kind: str, name: str) -> str:
    return f"{kind}:{' '.join(fold(name).split())}"[:220]


@lru_cache(maxsize=1)
def registry() -> dict:
    return yaml.safe_load((REGISTRY_DIR / "entities.yaml").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def known() -> list[Known]:
    out = []
    for e in registry()["entidades"]:
        out.append(
            Known(
                key=entity_key(e["kind"], e["name"]),
                name=e["name"],
                kind=e["kind"],
                country=e.get("country"),
                aliases=tuple(e.get("aliases", [])),
            )
        )
    return out


@lru_cache(maxsize=1)
def _gazetteer() -> tuple[re.Pattern, dict[str, list[tuple[str, Known]]]]:
    """Regex de todas las formas (sin tildes, minusculas) y, por forma, (escritura original, entidad)."""
    forms: dict[str, list[tuple[str, Known]]] = {}
    for k in known():
        for written in (k.name, *k.aliases):
            forms.setdefault(fold(written), []).append((written, k))
    alts = sorted(forms, key=len, reverse=True)
    rx = re.compile(r"(?<![\w-])(?:" + "|".join(re.escape(a) for a in alts) + r")(?![\w-])")
    return rx, forms


@lru_cache(maxsize=1)
def _given() -> frozenset[str]:
    return frozenset(registry()["nombres_de_pila"])


@lru_cache(maxsize=1)
def _heads() -> dict[str, str]:
    reg = registry()
    heads = {h: "institucion" for h in reg["cabezas_institucion"]}
    heads.update({h: "organizacion" for h in reg["cabezas_organizacion"]})
    return heads


def _case_ok(written: str, original: str) -> bool:
    """La forma escrita en el texto respeta la mayuscula del registro ("PP", "Sumar")."""
    if written.isupper() and len(written) > 1:
        return original.isupper()
    return original[:1].isupper() or not written[:1].isupper()


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    spans, start = [], 0
    for m in _SENTENCE.finditer(text):
        spans.append((start, m.start()))
        start = m.end()
    spans.append((start, len(text)))
    return [(a, b) for a, b in spans if b > a]


def _discover(text: str, folded: str, taken: list[tuple[int, int]]) -> list[tuple[int, int, str, str]]:
    """(inicio, fin, tipo, nombre) de nombres propios no cubiertos por el registro."""
    out = []
    given, heads = _given(), _heads()
    for m in _PROPER.finditer(text):
        end = m.end()
        tokens = [(t.start(), t.group(0)) for t in re.finditer(r"\S+", m.group(0))]
        # Quita palabras de cabecera que no son nombre ("Segun Pedro Garcia" -> "Pedro Garcia").
        while tokens and fold(tokens[0][1]) in _NOT_NAME:
            tokens = tokens[1:]
        if not tokens:
            continue
        start = m.start() + tokens[0][0]
        words = [w for _, w in tokens]
        if len(words) < 2 or any(s < end and start < e for s, e in taken):
            continue
        roman = _ROMAN.match(text, end)
        if roman:
            end = roman.end()
        name = text[start:end].strip(" -")
        first = fold(words[0])
        if first in given and fold(words[-1]) not in _NOT_NAME:
            trimmed = _ORG_ONLY.sub("", name)
            out.append((start, start + len(trimmed), "persona", trimmed))
        elif first in heads and len(words) >= 2:
            out.append((start, end, heads[first], name))
    return out


def extract(title: str, text: str = "") -> list[Found]:
    """Entidades de un titular y su texto, con cuantas veces aparecen y si hablan (con su frase)."""
    full = f"{title or ''}.\n{(text or '')[:TEXT_MAX]}"
    folded = fold(full)
    rx, forms = _gazetteer()
    found: dict[str, Found] = {}
    taken: list[tuple[int, int]] = []
    for m in rx.finditer(folded):
        original = full[m.start() : m.end()]
        for written, k in forms[m.group(0)]:
            if _case_ok(written, original):
                f = found.setdefault(k.key, Found(k.key, k.name, k.kind, k.country, curated=True))
                f.count += 1
                f.spans.append((m.start(), m.end()))
                taken.append((m.start(), m.end()))
                break
    for start, end, kind, name in _discover(full, folded, taken):
        key = entity_key(kind, name)
        f = found.setdefault(key, Found(key, name, kind))
        f.count += 1
        f.spans.append((start, end))
    # Una persona citada por su apellido despues de nombrarla entera ("Garcia dijo") suma a la misma.
    for f in list(found.values()):
        if f.kind != "persona" or f.curated or len(f.name.split()) < 2:
            continue
        surname = fold(f.name.split()[-1])
        for m in re.finditer(rf"(?<![\w-]){re.escape(surname)}(?![\w-])", folded):
            if full[m.start()].isupper() and not any(s <= m.start() < e for s, e in f.spans):
                f.count += 1
                f.spans.append((m.start(), m.end()))
    for a, b in _sentence_spans(full):
        sentence_f = folded[a:b]
        for f in found.values():
            if f.speaks or f.kind not in SPEAKER_KINDS:
                continue
            for s, e in f.spans:
                if a <= s < b and _speaks(sentence_f, s - a, e - a, full[a:b]):
                    f.speaks = True
                    f.quote = " ".join(full[a:b].split())[:QUOTE_MAX]
                    break
    return sorted(found.values(), key=lambda f: (-f.count, f.name))


def _speaks(sentence_folded: str, start: int, end: int, original: str) -> bool:
    if _SPEAKS_BEFORE.search(sentence_folded[max(0, start - 60) : start]):
        return True
    m = _SPEAKS_AFTER.match(sentence_folded[end : end + 110])
    if not m:
        return False
    # Un inciso que empieza por nombre propio es otra entidad ("El lider del PP, Feijoo, dijo"): habla ella.
    inciso = original[end + m.start("inciso") : end + m.end("inciso")] if m.group("inciso") else ""
    if inciso.lstrip(" ,")[:1].isupper():
        return False
    # Y si la entidad cierra el inciso de otra ("Laura F., portavoz de la Plataforma X, ha dicho"), tampoco.
    head = original[:start]
    return not ("," in head and head.rsplit(",", 1)[1].strip()[:1].islower())


def speaker_of(sentence: str, entities: list[Found] | None = None) -> Found | None:
    """Quien dice una frase (la de una afirmacion), si se puede atribuir con seguridad."""
    entities = entities if entities is not None else extract("", sentence)
    folded = fold(f".\n{sentence}")  # mismo desplazamiento que extract("", sentence)
    speakers = []
    for f in entities:
        if f.kind not in SPEAKER_KINDS:
            continue
        if any(_speaks(folded, s, e, f".\n{sentence}") for s, e in f.spans):
            speakers.append(f)
    if len(speakers) != 1:
        return None  # nadie o varios: no se adivina
    return speakers[0]
