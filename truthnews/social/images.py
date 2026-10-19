"""Imagen de cada pieza: la imagen social de su historia (Fase 4a) o, si no tiene, la de la marca."""

from __future__ import annotations

from pathlib import Path

from sqlalchemy.orm import Session

from truthnews import registry
from truthnews.analysis.compare import compare
from truthnews.models import Story, utcnow
from truthnews.web import queries, social

DEFAULT_IMAGE = Path(__file__).resolve().parent.parent / "web" / "static" / "og-default.png"


def story_png(session: Session, st: Story, lang: str, title: str | None = None) -> bytes:
    """PNG 1200x630 de una historia: titular, cifras en disputa y veredictos (lo mismo que `/og/...`)."""
    comp = compare(queries.story_articles(session, st.id))
    verdicts = queries.verdict_counts(session, [st.id]).get(st.id, {})
    kicker = (
        f"{registry.category_name(st.category, lang)} · {st.n_outlets} {registry.t(lang, 'outlets').lower()}"
    )
    disputes = [(d.noun, d.low, d.high, d.n_outlets) for d in comp.dispute_summaries()]
    return social.story_image(title or st.title, kicker, disputes, verdicts, registry.t(lang, "tagline"))


def image_for(
    session: Session, story_id: int | None, site_url: str, lang: str, title: str | None = None
) -> tuple[bytes, str]:
    """(PNG, URL publica) de la pieza; `title` sustituye al titular (p. ej. el traducido)."""
    st = session.get(Story, story_id) if story_id else None
    if st is None:
        return DEFAULT_IMAGE.read_bytes(), f"{site_url.rstrip('/')}/static/og-default.png"
    return story_png(session, st, lang, title), f"{site_url.rstrip('/')}/og/historia/{st.id}.png"


def today_png(session: Session, lang: str, fmt: str, site_domain: str, now=None) -> tuple[bytes, list]:
    """(PNG de "Hoy en 1 minuto", claves) en el formato pedido (ADR 0047)."""
    from truthnews.social import today  # perezoso: today importa la web

    now = now or utcnow()
    items = today.keys(session, now, lang)
    labels = [
        (
            k.verdict,
            registry.t(lang, "verdict_" + k.verdict) if k.verdict else registry.t(lang, "today_dispute"),
            k.sentence,
        )
        for k in items
    ]
    png = social.today_image(
        labels,
        registry.t(lang, "today_title"),
        now.strftime("%d/%m/%Y"),
        f"{site_domain}/hoy",
        registry.t(lang, "today_empty"),
        fmt,
    )
    return png, items
