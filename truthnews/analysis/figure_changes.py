"""Quien cambio su cifra (ADR 0032): revisiones de titular o extracto (ADR 0015), y del texto completo
(ADR 0052), que cambian una cifra.

Una revision cambia una cifra cuando la primera cifra de un mismo sustantivo (detenidos, muertos...) vale
distinto antes y despues. Se dice si el medio lo avisa en el texto nuevo ("actualiza", "eleva a",
"rectifica", "nuevo balance"...) o lo cambia en silencio. Los directos se excluyen: su titular rota cada
pocos minutos y no es una correccion. Mismo metodo para todos los medios; actualizar un balance no es un
error, por eso se muestra como dato y no entra en la exactitud del ranking (ADR 0021).
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from truthnews.analysis.compare import _LIVE, figures
from truthnews.classify import normalize
from truthnews.models import REVISION_MAX_CHARS, Article, ArticleRevision

MIN_CHANGES = 5  # por debajo, la proporcion de cambios en silencio no se da como porcentaje
_ANNOUNCED = re.compile(
    r"\b(actualiza|actualizad|actualizacion|rectifica|correccion|corrige|corregid|fe de errores|"
    r"nuevo balance|ultimo balance|eleva a|elevan a|eleva el balance|asciende a|ascienden a|"
    r"aumenta a|sube a|suben a|ya son|ya suman)"
)


@dataclass
class FigureChange:
    article: Article
    outlet: str
    field: str  # title | summary
    noun: str
    before: float
    after: float
    detected_at: datetime  # fecha de la version nueva (captura en que se detecto)
    announced: bool
    quote_before: str = ""
    quote_after: str = ""
    before_at: datetime | None = None  # fecha de la version anterior (captura previa)

    @property
    def silent(self) -> bool:
        return not self.announced


def _first_values(text: str) -> dict[str, float]:
    out: dict[str, float] = {}
    for noun, value, _, _ in figures(text):
        out.setdefault(noun, value)
    return out


def _diff(before: str, after: str) -> list[tuple[str, float, float, bool]]:
    b, a = _first_values(before), _first_values(after)
    announced = bool(_ANNOUNCED.search(normalize(after))) and not _ANNOUNCED.search(normalize(before))
    return [(n, b[n], a[n], announced) for n in b if n in a and b[n] != a[n]]


def changes_in(before: str, after: str) -> list[tuple[str, float, float, bool]]:
    """(sustantivo, antes, despues, avisado) de cada cifra que cambia entre dos versiones de un texto."""
    if _LIVE.search(normalize(before)) or _LIVE.search(normalize(after)):
        return []
    return _diff(before, after)


_SENTENCE = re.compile(r"(?<=[.!?…])\s+|\n+")


def _sentences(text: str) -> list[str]:
    return [s for s in (" ".join(p.split()) for p in _SENTENCE.split(text)) if s]


def _first_with(sentences: list[str], noun: str) -> str | None:
    return next((s for s in sentences if noun in _first_values(s)), None)


def _join(parts: list[str]) -> str:
    parts = list(dict.fromkeys(parts))
    each = REVISION_MAX_CHARS // len(parts) - 3  # cabe en la cita aunque cada frase sea larga
    return " … ".join(p if len(p) <= each else p[: each - 1] + "…" for p in parts)


def body_excerpts(before: str, after: str) -> tuple[str, str] | None:
    """Las frases del texto completo de antes y de despues donde cambia una cifra (ADR 0052), o None.

    Solo se guarda la cita, no el cuerpo (ADR 0003). Si el texto nuevo, y no el anterior, avisa del cambio,
    la frase del aviso va delante en el despues: asi `changes_in` sobre las citas da lo mismo que sobre
    los textos enteros. Un cuerpo largo cita «directo» sin serlo; los directos se descartan por el titular.
    """
    old, new = _sentences(before), _sentences(after)
    b_parts, a_parts = [], []
    for noun, _, _, _ in _diff(before, after):
        sb, sa = _first_with(old, noun), _first_with(new, noun)
        if sb and sa:
            b_parts.append(sb)
            a_parts.append(sa)
    if not b_parts:
        return None
    notice = next((s for s in new if _ANNOUNCED.search(normalize(s))), None)
    if notice and not _ANNOUNCED.search(normalize(before)):
        a_parts.insert(0, notice)
    b_ex, a_ex = _join(b_parts), _join(a_parts)
    return (b_ex, a_ex) if changes_in(b_ex, a_ex) else None


def figure_changes(revisions: list[ArticleRevision]) -> list[FigureChange]:
    # Fecha de la version anterior: la revision previa del mismo campo o, si no hay, la primera captura.
    previous: dict[int, datetime | None] = {}
    last: dict[tuple[int, str], datetime] = {}
    for r in sorted(revisions, key=lambda r: (r.detected_at, r.id)):
        previous[r.id] = last.get((r.article_id, r.field)) or (r.article.fetched_at if r.article else None)
        last[(r.article_id, r.field)] = r.detected_at
    out = []
    for r in revisions:
        if r.article is not None and _LIVE.search(normalize(r.article.title or "")):
            continue
        for noun, before, after, announced in changes_in(r.before, r.after):
            out.append(
                FigureChange(
                    r.article,
                    r.article.outlet.name if r.article else "",
                    r.field,
                    noun,
                    before,
                    after,
                    r.detected_at,
                    announced,
                    r.before,
                    r.after,
                    previous.get(r.id),
                )
            )
    return out


def _revisions(session: Session, *where) -> list[ArticleRevision]:
    q = (
        select(ArticleRevision)
        .options(joinedload(ArticleRevision.article).joinedload(Article.outlet))
        .where(*where)
        .order_by(ArticleRevision.detected_at.desc(), ArticleRevision.id.desc())
    )
    return list(session.scalars(q).unique())


def for_story(session: Session, story_id: int) -> list[FigureChange]:
    ids = select(Article.id).where(Article.story_id == story_id)
    return figure_changes(_revisions(session, ArticleRevision.article_id.in_(ids)))


def for_outlet(session: Session, outlet_id: int) -> list[FigureChange]:
    return figure_changes(_revisions(session, ArticleRevision.outlet_id == outlet_id))


@dataclass
class ChangeRecord:
    changes: int = 0
    silent: int = 0

    @property
    def enough(self) -> bool:
        return self.changes >= MIN_CHANGES

    @property
    def silent_share(self) -> int | None:
        return round(100 * self.silent / self.changes) if self.enough else None


def by_outlet(session: Session) -> dict[int, ChangeRecord]:
    """Cambios de cifra y cuantos en silencio, por medio (senal junto al ranking, no dentro)."""
    out: dict[int, ChangeRecord] = defaultdict(ChangeRecord)
    for c in figure_changes(_revisions(session)):
        rec = out[c.article.outlet_id]
        rec.changes += 1
        rec.silent += c.silent
    return dict(out)
