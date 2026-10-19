"""Que dicen los partidos: la IA propone de que historia habla cada declaracion; el codigo lo valida.

La IA solo agrupa (ADR 0007): elige, para cada declaracion, una historia de la lista o ninguna. Un id
de historia o de declaracion que no se le dio se descarta. La declaracion se muestra con su texto
original, su canal y su enlace; nada se reescribe. El coseno de titulares no sirve aqui (ADR 0024).
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews.ai.client import AIClient
from truthnews.models import PoliticalStatement, Story
from truthnews.registry import ActorSpec, load_political

log = logging.getLogger(__name__)

FRESH = timedelta(hours=3)  # cada declaracion se evalua en los ciclos de sus primeras 3 h
STORY_WINDOW = timedelta(hours=48)
MAX_STATEMENTS = 60
MAX_STORIES = 40

LINK_SYSTEM = """\
Recibes historias de actualidad (id y titular) y declaraciones publicadas por partidos politicos en sus
canales oficiales (id, partido y texto, en cualquier idioma). Para cada declaracion, indica el id de la
historia de la que habla directamente: el mismo hecho, decision o asunto concreto, no solo el mismo
tema general. Si no habla de ninguna de forma directa, devuelve null. Ante la duda, null. No valores
ni resumas las declaraciones; no favorezcas a ningun partido."""


def link_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "links": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "statement": {"type": "integer"},
                        "story": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
                    },
                    "required": ["statement", "story"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["links"],
        "additionalProperties": False,
    }


def run(session: Session, ai: AIClient, country: str, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    statements = list(
        session.scalars(
            select(PoliticalStatement)
            .where(
                PoliticalStatement.country == country,
                PoliticalStatement.story_id.is_(None),
                PoliticalStatement.fetched_at >= now - FRESH,
                PoliticalStatement.published_at >= now - STORY_WINDOW,
            )
            .order_by(PoliticalStatement.published_at.desc())
            .limit(MAX_STATEMENTS)
        )
    )
    stories = list(
        session.scalars(
            select(Story)
            .where(Story.country == country, Story.last_seen >= now - STORY_WINDOW, Story.n_outlets >= 2)
            .order_by(Story.priority.desc(), Story.n_outlets.desc())
            .limit(MAX_STORIES)
        )
    )
    if not statements or not stories:
        return {"statements": len(statements), "linked": 0}
    st_ids = {s.id for s in stories}
    by_id = {s.id: s for s in statements}
    user = "HISTORIAS\n" + "\n".join(f"{s.id}\t{s.title}" for s in stories)
    user += "\n\nDECLARACIONES\n" + "\n".join(f"{s.id}\t{s.actor}\t{s.text[:300]}" for s in statements)
    res = ai.structured(LINK_SYSTEM, user, link_schema())
    linked = 0
    for item in res.data.get("links", []):
        stmt, story = by_id.get(item.get("statement")), item.get("story")
        if stmt is None or story not in st_ids or stmt.story_id is not None:
            continue  # ids inventados, historias fuera de la lista o repetidos se descartan
        stmt.story_id = story
        linked += 1
    session.commit()
    out = {"statements": len(statements), "linked": linked}
    log.info("declaraciones enlazadas: %s", out)
    return out


def for_story(session: Session, story: Story, actors: list[ActorSpec] | None = None) -> list[dict]:
    """Una fila por partido del pais, en orden alfabetico y con el mismo formato: sus declaraciones sobre
    la historia (las 2 mas recientes) o ninguna. Vacio si ningun partido ha dicho nada enlazado."""
    rows = session.scalars(
        select(PoliticalStatement)
        .where(PoliticalStatement.story_id == story.id)
        .order_by(PoliticalStatement.published_at.desc())
    ).all()
    if not rows:
        return []
    actors = [a for a in (actors if actors is not None else load_political()) if a.country == story.country]
    said: dict[str, list] = {}
    for r in rows:
        said.setdefault(r.actor, []).append(r)
    return [{"actor": a, "statements": said.get(a.slug, [])[:2]} for a in actors]
