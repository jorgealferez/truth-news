"""Paso de IA del ciclo del worker: temas y piezas, con presupuesto por ciclo (ADR 0007)."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from truthnews.ai import cost, statements, translate
from truthnews.ai.client import AIClient, AIError
from truthnews.ai.topics import build_topics
from truthnews.ai.writer import ask_piece, prepare_piece, store_pieces
from truthnews.analysis import abroad
from truthnews.analysis.verify import Verifier
from truthnews.config import Settings
from truthnews.models import Piece, Topic, utcnow

log = logging.getLogger(__name__)


def run(
    session: Session,
    settings: Settings,
    ai: AIClient | None = None,
    verifier: Verifier | None = None,
    translator: AIClient | None = None,
) -> dict:
    if ai is None and not settings.ai_enabled:
        return {"ai": "desactivada (sin ANTHROPIC_API_KEY)"}
    injected = ai is not None
    ai = ai or AIClient(settings.ai_model, settings.ai_effort)
    out: dict = {}
    spent = _Spent()  # USD de cada parte del paso, para decidir con cifras donde ahorrar (ADR 0054)
    # Traducir y enlazar declaraciones no razona: esfuerzo bajo y cliente propio, no el de temas (ADR 0017).
    translator = translator or (None if injected else AIClient(settings.ai_model, "low", max_tokens=16000))
    if translator is not None:
        try:  # titulares de otros idiomas al de la portada; despues al ingles, con su propio tope
            out["translations"] = translate.run(
                session, translator, [settings.default_language], settings.ai_max_translations_per_cycle
            )
            if settings.default_language != "en":
                out["translations"].update(
                    translate.run(session, translator, ["en"], settings.ai_max_translations_en_per_cycle)
                )
        except AIError as exc:
            session.rollback()
            log.warning("traducciones no generadas: %s", exc)
    spent.mark("traducciones")
    # La misma historia en otros paises, con los titulares ya traducidos (ADR 0022).
    out["abroad"] = abroad.link(session, settings.default_country, settings.default_language)
    session.commit()
    if translator is not None:
        try:  # que dicen los partidos: la IA propone la historia y el codigo valida los ids (ADR 0024)
            out["statements"] = statements.run(session, translator, settings.default_country)
        except AIError as exc:
            session.rollback()
            log.warning("declaraciones no enlazadas: %s", exc)
    spent.mark("declaraciones")
    try:
        out["topics"] = build_topics(session, ai, settings.default_country)
        session.commit()
    except AIError as exc:
        log.warning("temas no generados: %s", exc)
        return {"error": str(exc), "coste_usd": spent.mark("temas")}
    spent.mark("temas")
    topics = session.scalars(
        select(Topic)
        .where(Topic.country == settings.default_country)
        .order_by(Topic.n_outlets.desc(), Topic.last_seen.desc())
        .limit(settings.ai_max_pieces_per_cycle * 2)
    )
    written, revision, failed = write_batch(
        session,
        ai,
        topics,
        verifier or Verifier(),
        settings.ai_max_pieces_per_cycle,
        settings.ai_piece_concurrency,
        timedelta(minutes=settings.ai_piece_refresh_minutes),
    )
    out.update({"pieces_written": written, "pieces_in_revision": revision, "failed": failed})
    out["coste_usd"] = spent.mark("piezas")
    log.info("IA: %s", out)
    return out


class _Spent:
    """Coste de la IA por parte del paso: lo que subio el contador del ciclo desde la marca anterior."""

    def __init__(self):
        self._last = cost.METER.spent
        self.parts: dict[str, float] = {}

    def mark(self, part: str) -> dict[str, float]:
        now = cost.METER.spent
        self.parts[part] = round(now - self._last, 4)
        self._last = now
        return self.parts


def recent_piece(session: Session, topic: Topic, refresh: timedelta) -> bool:
    """El tema tiene una pieza de hace menos de `refresh`: no se paga otra aunque el dossier haya cambiado."""
    last = session.scalar(select(func.max(Piece.created_at)).where(Piece.topic_id == topic.id))
    if last is None:
        return False
    return (last if last.tzinfo else last.replace(tzinfo=UTC)) > utcnow() - refresh


def write_batch(
    session, ai, topics, verifier, max_pieces: int, concurrency: int, refresh: timedelta | None = None
) -> tuple[int, int, int]:
    """(escritas, en revision, fallidas). Las llamadas de las piezas van en paralelo (2-2,5 min cada una con
    esfuerzo alto: en serie eran la mitad del ciclo); los dossieres se preparan y las piezas se guardan en
    serie y en orden, porque la sesion no se comparte entre hilos. Con `refresh`, un tema con pieza reciente
    cede su plaza al siguiente (ADR 0054)."""
    batch = []
    for topic in topics:
        if len(batch) >= max_pieces:
            break
        if refresh and recent_piece(session, topic, refresh):
            continue
        prepared = prepare_piece(session, topic, verifier)
        if prepared is not None:
            batch.append((topic, *prepared))
    written = revision = failed = 0
    with ThreadPoolExecutor(max_workers=max(1, concurrency)) as pool:
        futures = [(topic, dossier, h, pool.submit(ask_piece, ai, dossier)) for topic, dossier, h in batch]
        for topic, dossier, h, future in futures:
            try:
                pieces = store_pieces(session, topic, dossier, h, future.result())
            except AIError as exc:
                log.warning("pieza del tema %s no generada: %s", topic.id, exc)
                failed += 1
                continue
            session.commit()  # cada pieza queda guardada aunque el ciclo se corte (p. ej. un redespliegue)
            written += 1
            revision += pieces[0].status == "revision"
    return written, revision, failed
