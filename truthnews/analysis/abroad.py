"""La misma historia contada en otros paises: enlaza cada historia con la cobertura de medios extranjeros.

Los articulos de otros paises no entran en la historia (el comparador los juzgaria con palabras de otro
idioma); se enlazan aparte (ADR 0022). Se compara el titular en el idioma de la portada: el original si
ya lo esta, o su traduccion con IA (ADR 0017). Sin texto comparable, el articulo no se enlaza.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, joinedload

from truthnews.analysis.cluster import Doc, cosine, idf_table, vectorize
from truthnews.models import Article, ArticleTranslation, Story, StoryAbroad

THRESHOLD = 0.40  # mas exigente que el agrupador (0,30): solo se compara el titular
WINDOW = timedelta(hours=48)
MAX_STORIES = 80
PER_STORY = 12
PER_COUNTRY = 3
# Contenido seriado que comparte casi todo el titular de un dia a otro: no es "la misma historia" (medido
# en produccion 2026-10-19: 3 de los 3 enlaces fallidos de una muestra de 63 eran horoscopos).
NO_LINK = re.compile(r"hor[oó]scopo", re.IGNORECASE)


def centroid(vectors: list[dict[str, float]]) -> dict[str, float]:
    acc: dict[str, float] = defaultdict(float)
    for vec in vectors:
        for k, v in vec.items():
            acc[k] += v
    norm = sum(v * v for v in acc.values()) ** 0.5 or 1.0
    return {k: v / norm for k, v in acc.items()}


def match(
    stories: dict[int, list[str]],
    candidates: list[tuple[Doc, str]],
    threshold: float = THRESHOLD,
    per_story: int = PER_STORY,
    per_country: int = PER_COUNTRY,
) -> dict[int, list[tuple[object, float]]]:
    """`stories`: id -> titulares; `candidates`: (doc, pais). Devuelve id -> [(clave, similitud)]."""
    docs = [Doc(key=("s", sid, i), title=t) for sid, ts in stories.items() for i, t in enumerate(ts)]
    idf = idf_table(docs + [d for d, _ in candidates])
    cvecs = [(d, country, vectorize(d, idf)) for d, country in candidates]
    out: dict[int, list[tuple[object, float]]] = {}
    for sid, titles in stories.items():
        cen = centroid([vectorize(Doc(key=None, title=t), idf) for t in titles])
        scored = sorted(
            ((cosine(vec, cen), d.key, country) for d, country, vec in cvecs), key=lambda x: -x[0]
        )
        picked, by_country = [], defaultdict(int)
        for sim, key, country in scored:
            if sim < threshold or len(picked) >= per_story:
                break
            if by_country[country] >= per_country:
                continue
            by_country[country] += 1
            picked.append((key, round(sim, 3)))
        if picked:
            out[sid] = picked
    return out


def link(session: Session, country: str, lang: str, now: datetime | None = None) -> dict:
    """Recalcula los enlaces de las historias activas de `country` con articulos de otros paises."""
    now = now or datetime.now(UTC)
    stories = list(
        session.scalars(
            select(Story)
            .where(Story.country == country, Story.last_seen >= now - WINDOW, Story.n_outlets >= 2)
            .order_by(Story.priority.desc(), Story.n_outlets.desc())
            .limit(MAX_STORIES)
        )
    )
    if not stories:
        return {"stories": 0, "links": 0}
    ids = [s.id for s in stories]  # se recalculan todas, tambien las que dejan de enlazarse
    linkable = {s.id for s in stories if not NO_LINK.search(s.title)}
    titles: dict[int, list[str]] = defaultdict(list)
    for sid, title in session.execute(
        select(Article.story_id, Article.title).where(Article.story_id.in_(linkable))
    ):
        titles[sid].append(title)
    foreign = session.execute(
        select(Article, ArticleTranslation.title)
        .options(joinedload(Article.outlet))
        .outerjoin(
            ArticleTranslation,
            (ArticleTranslation.article_id == Article.id) & (ArticleTranslation.lang == lang),
        )
        .where(Article.country != country, Article.published_at >= now - WINDOW - timedelta(hours=24))
    ).all()
    candidates = []
    for art, translated in foreign:
        text = art.title if art.language == lang else translated
        if text:
            candidates.append((Doc(key=art.id, title=text), art.outlet.country))
    links = match(dict(titles), candidates)
    session.execute(delete(StoryAbroad).where(StoryAbroad.story_id.in_(ids)))
    n = 0
    for sid, picked in links.items():
        for article_id, sim in picked:
            session.add(StoryAbroad(story_id=sid, article_id=article_id, similarity=sim, linked_at=now))
            n += 1
    session.flush()
    return {"stories": len(stories), "candidates": len(candidates), "links": n}


def for_story(session: Session, story_id: int) -> list[Article]:
    q = (
        select(Article)
        .join(StoryAbroad, StoryAbroad.article_id == Article.id)
        .options(joinedload(Article.outlet))
        .where(StoryAbroad.story_id == story_id)
        .order_by(StoryAbroad.similarity.desc())
    )
    return list(session.scalars(q))
