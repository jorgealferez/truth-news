"""Proceso worker: rastreo periodico (y, en fases siguientes, analisis y distribucion)."""

from __future__ import annotations

import asyncio
import logging

from apscheduler.schedulers.blocking import BlockingScheduler

from truthnews.ai import threads
from truthnews.ai.client import AIClient, AIError
from truthnews.ai.pipeline import run as ai_step
from truthnews.analysis.pipeline import run as analyze
from truthnews.config import Settings, get_settings
from truthnews.crawler.ingest import crawl, sync_registry
from truthnews.db import get_engine, session_scope
from truthnews.investigate import process_pending, seed_defaults

log = logging.getLogger(__name__)


def run_cycle(settings: Settings | None = None) -> dict:
    settings = settings or get_settings()
    engine = get_engine(settings.database_url)
    with session_scope(engine) as session:
        sync_registry(session)
    with session_scope(engine) as session:
        run = asyncio.run(crawl(session, settings))
        summary = {
            "run": run.id,
            "feeds_ok": run.feeds_ok,
            "feeds_failed": run.feeds_failed,
            "articles_new": run.articles_new,
            "robots_blocked": run.robots_blocked,
        }
        started = run.started_at
    with session_scope(engine) as session:
        summary["analysis"] = analyze(session, since=started)
    if settings.ai_enabled:  # los hilos van primero: son lo que mas aporta (peticion del usuario 2026-10-19)
        with session_scope(engine) as session:
            try:
                summary["threads"] = threads.run(
                    session,
                    AIClient(settings.ai_model, settings.ai_effort),
                    settings.default_country,
                    settings.ai_max_threads_per_cycle,
                )
            except AIError as exc:
                summary["threads"] = {"error": str(exc)}
    with session_scope(engine) as session:
        summary["ai"] = ai_step(session, settings)
    with session_scope(engine) as session:
        seed_defaults(session)
        ai = AIClient(settings.ai_model, settings.ai_effort) if settings.ai_enabled else None
        summary["investigations"] = process_pending(session, ai=ai)
    log.info("ciclo terminado: %s", summary)
    return summary


def main(settings: Settings | None = None) -> None:  # pragma: no cover - bucle infinito
    settings = settings or get_settings()
    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        run_cycle,
        "interval",
        minutes=settings.crawl_interval_minutes,
        args=[settings],
        id="crawl",
        max_instances=1,
        coalesce=True,
        next_run_time=None,
    )
    log.info("worker: primer ciclo inmediato, despues cada %s min", settings.crawl_interval_minutes)
    try:
        run_cycle(settings)
    except Exception:
        log.exception("el primer ciclo fallo; el planificador lo reintentara")
    scheduler.start()
