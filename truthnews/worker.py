"""Proceso worker: rastreo periodico (y, en fases siguientes, analisis y distribucion)."""

from __future__ import annotations

import asyncio
import logging
import threading
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from truthnews.ai import claims as ai_claims
from truthnews.ai import threads
from truthnews.ai.client import AIClient, AIError
from truthnews.ai.pipeline import run as ai_step
from truthnews.analysis.pipeline import run as analyze
from truthnews.analysis.score import score_stories
from truthnews.config import Settings, get_settings
from truthnews.crawler import political
from truthnews.crawler.ingest import crawl, sync_registry
from truthnews.db import get_engine, session_scope
from truthnews.investigate import process_pending, seed_defaults
from truthnews.models import CrawlRun, Outlet
from truthnews.social import queue as social

log = logging.getLogger(__name__)
RECENT_CYCLE_MIN = 25  # los agentes despliegan a menudo; cada arranque no debe pagar un ciclo completo
BREAKING_LANE = "rapido"  # marca en CrawlRun.stats de los rastreos del carril de ultimo minuto
_busy = threading.Lock()  # el ciclo completo y el carril rapido nunca se solapan


def run_cycle(settings: Settings | None = None) -> dict:
    with _busy:
        return _run_cycle(settings or get_settings())


def breaking_outlets(session, country: str) -> list[str]:
    """Medios nacionales del pais (agencias, diarios, radio y television): los que dan el ultimo minuto."""
    q = select(Outlet.slug).where(
        Outlet.active.is_(True), Outlet.country == country, Outlet.scope == "national"
    )
    return list(session.scalars(q))


def run_breaking(settings: Settings | None = None) -> dict | None:
    """Carril rapido: rastreo de los medios nacionales y contraste con datos, sin IA (barato y frecuente).

    Si el ciclo completo esta en marcha no se espera: ese ciclo ya rastrea todo."""
    settings = settings or get_settings()
    if not _busy.acquire(blocking=False):
        log.info("ultimo minuto: ciclo completo en marcha, se salta esta vuelta")
        return None
    try:
        engine = get_engine(settings.database_url)
        with session_scope(engine) as session:
            slugs = breaking_outlets(session, settings.default_country)
            if not slugs:
                return None
            run = asyncio.run(crawl(session, settings, outlet_slugs=slugs))
            run.stats = {**(run.stats or {}), "lane": BREAKING_LANE}
            summary = {
                "run": run.id,
                "lane": BREAKING_LANE,
                "outlets": len(slugs),
                "articles_new": run.articles_new,
            }
            started = run.started_at
        with session_scope(engine) as session:
            summary["analysis"] = analyze(session, since=started)
        log.info("ultimo minuto terminado: %s", summary)
        return summary
    finally:
        _busy.release()


def _run_cycle(settings: Settings) -> dict:
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
    with session_scope(engine) as session:  # partidos en sus canales oficiales verificados (ADR 0024)
        try:
            summary["political"] = political.run(session, settings)
        except Exception as exc:  # un canal o un partido caido no tumba el ciclo
            log.exception("declaraciones politicas: el paso fallo")
            session.rollback()
            summary["political"] = {"error": str(exc)[:300]}
    if settings.ai_enabled:  # mas afirmaciones juzgadas: la prioridad del usuario (2026-10-19)
        with session_scope(engine) as session:
            ai = AIClient(settings.ai_model, settings.ai_claims_effort, max_tokens=16000)
            summary["ai_claims"] = ai_claims.run(session, ai, started, max_calls=settings.ai_claims_max_calls)
            summary["ai_claims"]["scores"] = score_stories(session, started)
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
    with session_scope(engine) as session:  # redes al final: publica lo que este ciclo dejo listo (ADR 0018)
        try:
            summary["social"] = social.run(session, settings.site_url, lang=settings.default_language)
        except Exception as exc:  # una red caida no tumba el ciclo
            log.exception("redes: el paso fallo")
            session.rollback()
            summary["social"] = {"error": str(exc)[:300]}
    log.info("ciclo terminado: %s", summary)
    return summary


def recent_cycle(settings: Settings, now: datetime | None = None) -> bool:
    """Hubo un ciclo hace menos de RECENT_CYCLE_MIN: un redespliegue no debe repetirlo (ni su coste de IA)."""
    now = now or datetime.now(UTC)
    engine = get_engine(settings.database_url)
    with session_scope(engine) as session:
        rows = session.execute(
            select(CrawlRun.started_at, CrawlRun.stats).order_by(CrawlRun.id.desc()).limit(50)
        )
        # Los rastreos del carril rapido no cuentan: no hacen el trabajo del ciclo completo (IA, redes).
        last = next((at for at, stats in rows if (stats or {}).get("lane") != BREAKING_LANE), None)
    if last is None:
        return False
    last = last if last.tzinfo else last.replace(tzinfo=UTC)
    return now - last < timedelta(minutes=RECENT_CYCLE_MIN)


def add_jobs(scheduler, settings: Settings) -> None:
    """Ciclo completo cada crawl_interval_minutes y carril de ultimo minuto cada breaking_interval_minutes."""
    scheduler.add_job(
        run_cycle,
        "interval",
        minutes=settings.crawl_interval_minutes,
        args=[settings],
        id="crawl",
        max_instances=1,
        coalesce=True,
        # Sin next_run_time=None: en APScheduler 3 eso deja el trabajo en pausa y el ciclo horario solo
        # ocurria al redesplegar. El primero cae a +intervalo; el del arranque se lanza a mano abajo.
    )
    if settings.breaking_interval_minutes > 0:
        scheduler.add_job(
            run_breaking,
            "interval",
            minutes=settings.breaking_interval_minutes,
            args=[settings],
            id="breaking",
            max_instances=1,
            coalesce=True,
        )


def main(settings: Settings | None = None) -> None:  # pragma: no cover - bucle infinito
    settings = settings or get_settings()
    scheduler = BlockingScheduler(timezone="UTC")
    add_jobs(scheduler, settings)
    if recent_cycle(settings):
        log.info(
            "worker: ciclo reciente (redespliegue); el siguiente, en %s min", settings.crawl_interval_minutes
        )
    else:
        log.info("worker: primer ciclo inmediato, despues cada %s min", settings.crawl_interval_minutes)
        try:
            run_cycle(settings)
        except Exception:
            log.exception("el primer ciclo fallo; el planificador lo reintentara")
    scheduler.start()
