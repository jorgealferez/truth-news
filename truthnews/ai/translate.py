"""Titulares traducidos con IA a los idiomas de la interfaz, guardados aparte y marcados (ADR 0017).

Solo se traduce el titular de articulos de historias activas; el original queda intacto y es el que se
cita. La IA traduce, no resume ni interpreta (ADR 0007): un id que no se le dio se descarta.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from truthnews.ai.client import AIClient
from truthnews.models import Article, ArticleTranslation, Story

log = logging.getLogger(__name__)

BATCH = 40
WINDOW = timedelta(hours=48)
LANG_NAMES = {"es": "espanol", "en": "ingles"}

TRANSLATE_SYSTEM = """\
Eres traductor de titulares de prensa. Traduce cada titular al idioma pedido de forma fiel y literal:
mismo sentido, mismas cifras, mismos nombres propios, mismas comillas y atribuciones. No resumas, no
anadas contexto, no suavices ni endurezcas el tono, no corrijas al medio. Si un titular ya esta en el
idioma pedido, devuelvelo igual. Devuelve un elemento por cada id recibido, con el mismo id."""


def translate_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"id": {"type": "integer"}, "title": {"type": "string"}},
                    "required": ["id", "title"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["items"],
        "additionalProperties": False,
    }


def pending(session: Session, lang: str, limit: int, now: datetime | None = None) -> list[Article]:
    """Articulos de historias con actividad reciente, en otro idioma y sin traduccion a `lang`."""
    since = (now or datetime.now(UTC)) - WINDOW
    q = (
        select(Article)
        .join(Story, Article.story_id == Story.id)
        .outerjoin(
            ArticleTranslation,
            and_(ArticleTranslation.article_id == Article.id, ArticleTranslation.lang == lang),
        )
        .where(Story.last_seen >= since, Article.language != lang, ArticleTranslation.id.is_(None))
        .order_by(Story.priority.desc(), Story.n_outlets.desc(), Article.published_at.desc())
        .limit(limit)
    )
    return list(session.scalars(q))


def translate_batch(session: Session, ai: AIClient, lang: str, articles: list[Article]) -> int:
    by_id = {a.id: a for a in articles}
    lines = "\n".join(f"{a.id}\t[{a.language}] {a.title}" for a in articles)
    user = f"Idioma de destino: {LANG_NAMES.get(lang, lang)} ({lang}).\nid\t[idioma] titular\n{lines}"
    res = ai.structured(TRANSLATE_SYSTEM, user, translate_schema())
    saved = 0
    for item in res.data.get("items", []):
        art = by_id.pop(item.get("id"), None)  # ids inventados o repetidos se descartan
        title = (item.get("title") or "").strip()
        if art is None or not title:
            continue
        session.add(ArticleTranslation(article_id=art.id, lang=lang, title=title[:600], model=res.model))
        saved += 1
    return saved


def run(session: Session, ai: AIClient, langs: list[str], max_per_cycle: int) -> dict:
    """Traduce hasta `max_per_cycle` titulares por ciclo, repartidos entre los idiomas de destino."""
    out: dict = {}
    budget = max_per_cycle
    for lang in langs:
        done = 0
        while budget > 0:
            batch = pending(session, lang, min(BATCH, budget))
            if not batch:
                break
            n = translate_batch(session, ai, lang, batch)
            session.commit()  # cada lote queda guardado aunque el ciclo se corte
            budget -= len(batch)
            done += n
            if n == 0:  # el modelo no devolvio nada aprovechable: no se reintenta en bucle
                break
        out[lang] = done
    log.info("traducciones: %s", out)
    return out


def titles(session: Session, article_ids: list[int], lang: str) -> dict[int, str]:
    if not article_ids:
        return {}
    q = select(ArticleTranslation.article_id, ArticleTranslation.title).where(
        ArticleTranslation.article_id.in_(article_ids), ArticleTranslation.lang == lang
    )
    return dict(session.execute(q).all())
