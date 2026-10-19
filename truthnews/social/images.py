"""Imagen de cada pieza: la imagen social de su historia (Fase 4a) o, si no tiene, la de la marca."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from truthnews import registry
from truthnews.analysis.compare import compare
from truthnews.models import Story
from truthnews.web import queries, social

DEFAULT_IMAGE = Path(__file__).resolve().parent.parent / "web" / "static" / "og-default.png"


def story_png(session: Session, st: Story, lang: str) -> bytes:
    """PNG 1200x630 de una historia: titular, cifras en disputa y veredictos (lo mismo que `/og/...`)."""
    comp = compare(queries.story_articles(session, st.id))
    verdicts = queries.verdict_counts(session, [st.id]).get(st.id, {})
    kicker = f"{registry.category_name(st.category, lang)} · {st.n_outlets} medios"
    disputes = [(d.noun, d.low, d.high, d.n_outlets) for d in comp.dispute_summaries()]
    return social.story_image(st.title, kicker, disputes, verdicts, registry.t(lang, "tagline"))


def image_for(session: Session, story_id: int | None, site_url: str, lang: str) -> tuple[bytes, str]:
    """(PNG, URL publica) de la pieza."""
    st = session.get(Story, story_id) if story_id else None
    if st is None:
        return DEFAULT_IMAGE.read_bytes(), f"{site_url.rstrip('/')}/static/og-default.png"
    return story_png(session, st, lang), f"{site_url.rstrip('/')}/og/historia/{st.id}.png"
