"""Agrupacion de historias en temas con IA (ADR 0007) y persistencia con identidad estable."""

from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from truthnews.ai.client import AIClient
from truthnews.ai.prompts import TOPICS_SYSTEM
from truthnews.models import Article, Story, Topic, utcnow
from truthnews.registry import categories

log = logging.getLogger(__name__)
MAX_STORIES = 150


def topics_schema() -> dict:
    return {
        "type": "object",
        "properties": {
            "temas": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "titulo": {"type": "string"},
                        "categoria": {"type": "string", "enum": list(categories())},
                        "historias": {"type": "array", "items": {"type": "integer"}},
                    },
                    "required": ["titulo", "categoria", "historias"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["temas"],
        "additionalProperties": False,
    }


def candidate_stories(session: Session, country: str, hours: int = 72) -> list[Story]:
    since = utcnow() - timedelta(hours=hours)
    q = (
        select(Story)
        .where(Story.country == country, Story.n_outlets >= 2, Story.last_seen >= since)
        .order_by(Story.n_outlets.desc(), Story.last_seen.desc())
        .limit(MAX_STORIES)
    )
    return list(session.scalars(q))


def build_topics(session: Session, ai: AIClient, country: str = "ES") -> dict:
    stories = candidate_stories(session, country)
    if len(stories) < 2:
        return {"topics": 0, "stories": len(stories)}
    payload = [
        {"id": s.id, "titular": s.title, "categoria": s.category, "medios": s.n_outlets} for s in stories
    ]
    user = (
        "Categorias validas: "
        + ", ".join(categories())
        + "\n\nHistorias:\n"
        + json.dumps(payload, ensure_ascii=False)
    )
    result = ai.structured(TOPICS_SYSTEM, user, topics_schema())
    by_id = {s.id: s for s in stories}
    assigned: set[int] = set()
    clean = []
    for t in result.data.get("temas", []):
        ids = [i for i in t["historias"] if i in by_id and i not in assigned]
        if len(ids) < 2 or t["categoria"] not in categories():
            continue  # la IA no puede inventar historias ni temas de una sola
        assigned.update(ids)
        clean.append((t["titulo"][:300], t["categoria"], ids))
    for s in stories:
        if s.id not in assigned and s.topic_id is not None:
            s.topic_id = None
    created = 0
    used: set[int] = set()
    for title, category, ids in clean:
        members = [by_id[i] for i in ids]
        votes = Counter(m.topic_id for m in members if m.topic_id and m.topic_id not in used)
        topic = session.get(Topic, votes.most_common(1)[0][0]) if votes else None
        if topic is None:
            topic = Topic(
                title=title,
                category=category,
                country=country,
                first_seen=min(m.first_seen for m in members),
                last_seen=max(m.last_seen for m in members),
            )
            session.add(topic)
            session.flush()
            created += 1
        used.add(topic.id)
        topic.title, topic.category = title, category
        topic.first_seen = min(m.first_seen for m in members)
        topic.last_seen = max(m.last_seen for m in members)
        topic.n_stories = len(members)
        topic.updated_at = utcnow()
        for m in members:
            m.topic_id = topic.id
        session.flush()
        topic.n_outlets = len(
            {
                a.outlet_id
                for m in members
                for a in session.scalars(select(Article).where(Article.story_id == m.id))
            }
        )
    session.flush()
    return {"topics": len(clean), "topics_created": created, "stories": len(stories), "usage": result.usage}


def topic_articles(session: Session, topic: Topic) -> list[Article]:
    q = (
        select(Article)
        .options(joinedload(Article.outlet), joinedload(Article.story))
        .join(Story, Story.id == Article.story_id)
        .where(Story.topic_id == topic.id)
        .order_by(Article.published_at)
    )
    return list(session.scalars(q))
