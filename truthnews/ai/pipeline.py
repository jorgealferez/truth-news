"""Paso de IA del ciclo del worker: temas y piezas, con presupuesto por ciclo (ADR 0007)."""

from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from truthnews.ai.client import AIClient, AIError
from truthnews.ai.topics import build_topics
from truthnews.ai.writer import write_pieces
from truthnews.analysis.verify import Verifier
from truthnews.config import Settings
from truthnews.models import Topic

log = logging.getLogger(__name__)


def run(
    session: Session, settings: Settings, ai: AIClient | None = None, verifier: Verifier | None = None
) -> dict:
    if ai is None and not settings.ai_enabled:
        return {"ai": "desactivada (sin ANTHROPIC_API_KEY)"}
    ai = ai or AIClient(settings.ai_model, settings.ai_effort)
    out: dict = {}
    try:
        out["topics"] = build_topics(session, ai, settings.default_country)
    except AIError as exc:
        log.warning("temas no generados: %s", exc)
        return {"error": str(exc)}
    topics = session.scalars(
        select(Topic)
        .where(Topic.country == settings.default_country)
        .order_by(Topic.n_outlets.desc(), Topic.last_seen.desc())
        .limit(settings.ai_max_pieces_per_cycle * 2)
    )
    written = revision = failed = 0
    for topic in topics:
        if written >= settings.ai_max_pieces_per_cycle:
            break
        try:
            pieces = write_pieces(session, topic, ai, verifier or Verifier())
        except AIError as exc:
            log.warning("pieza del tema %s no generada: %s", topic.id, exc)
            failed += 1
            continue
        if pieces:
            written += 1
            revision += pieces[0].status == "revision"
    out.update({"pieces_written": written, "pieces_in_revision": revision, "failed": failed})
    log.info("IA: %s", out)
    return out
