"""Proceso worker: rastreo periodico (y, en fases siguientes, analisis y distribucion)."""

from __future__ import annotations

import asyncio
import logging
import threading
import time
from datetime import UTC, datetime, timedelta

from apscheduler.schedulers.blocking import BlockingScheduler
from sqlalchemy import select

from truthnews import archive
from truthnews.ai import claims as ai_claims
from truthnews.ai import threads
from truthnews.ai.client import AIClient, AIError
from truthnews.ai.pipeline import run as ai_step
from truthnews.analysis import statement_checks
from truthnews.analysis.pipeline import run as analyze
from truthnews.analysis.score import score_stories
from truthnews.config import Settings, get_settings
from truthnews.crawler import political
from truthnews.crawler.ingest import crawl, sync_registry
from truthnews.db import get_engine, session_scope
from truthnews.entities import store as entities
from truthnews.investigate import process_pending, seed_defaults
from truthnews.models import CrawlRun, Outlet, utcnow
from truthnews.social import queue as social

log = logging.getLogger(__name__)
FULL_CYCLE = "terminado"  # marca en CrawlRun.stats del ciclo completo que llego al final
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


class _Timed(dict):
    """Resumen del ciclo que anota cuanto tardo cada paso (en `seconds`): los pasos van en serie y cada uno
    escribe su clave al terminar, asi que el tiempo entre dos claves es lo que tardo ese paso."""

    def __init__(self, clock=time.monotonic):
        super().__init__()
        self._clock = clock
        self._last = clock()
        self.seconds: dict[str, float] = {}

    def __setitem__(self, key, value):
        now = self._clock()
        self.seconds.setdefault(key, round(now - self._last, 1))
        self._last = now
        super().__setitem__(key, value)


def _run_cycle(settings: Settings) -> dict:
    engine = get_engine(settings.database_url)
    summary = _Timed()
    with session_scope(engine) as session:
        sync_registry(session)
    with session_scope(engine) as session:
        run = asyncio.run(crawl(session, settings))
        summary["run"] = run.id  # seconds["run"]: registro y rastreo
        summary.update(  # `update` no pasa por __setitem__: no son pasos
            feeds_ok=run.feeds_ok,
            feeds_failed=run.feeds_failed,
            articles_new=run.articles_new,
            robots_blocked=run.robots_blocked,
        )
        started = run.started_at
    with session_scope(engine) as session:
        summary["analysis"] = analyze(session, since=started)
    with session_scope(engine) as session:  # partidos en sus canales oficiales verificados (ADR 0024)
        try:
            summary["political"] = political.run(session, settings)  # sin Wikidata: robots.txt lo prohibe
        except Exception as exc:  # un canal o un partido caido no tumba el ciclo
            log.exception("declaraciones politicas: el paso fallo")
            session.rollback()
            summary["political"] = {"error": str(exc)[:300]}
    # Lo que dicen los partidos en sus canales, juzgado con el mismo juez que las noticias (ADR 0031).
    summary["statement_checks"] = _guarded(engine, "declaraciones juzgadas", statement_checks.run)
    if settings.ai_enabled:  # mas afirmaciones juzgadas: la prioridad del usuario (2026-10-19)
        with session_scope(engine) as session:
            ai = AIClient(settings.ai_model, settings.ai_claims_effort, max_tokens=16000)
            summary["ai_claims"] = ai_claims.run(session, ai, started, max_calls=settings.ai_claims_max_calls)
            summary["ai_claims"]["scores"] = score_stories(session, started)
    # Entidades tras el analisis (las afirmaciones ya existen y se les atribuye quien las dice) y, despues,
    # archivo de las entidades; lo importado se extrae en el ciclo siguiente (ADR 0028).
    summary["entities"] = _guarded(
        engine, "entidades", lambda s: entities.process(s, settings.entities_batch)
    )
    if settings.archive_slots_per_cycle > 0:
        summary["archive"] = _guarded(
            engine,
            "archivo",
            lambda s: archive.run(
                s,
                slots=settings.archive_slots_per_cycle,
                stride=timedelta(minutes=settings.archive_stride_minutes),
                countries=settings.archive_countries,
            ),
        )
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
    with session_scope(engine) as session:  # solo cuenta un ciclo que llega aqui (no uno cortado a medias)
        row = session.get(CrawlRun, summary["run"])
        if row is not None:
            row.stats = {
                **(row.stats or {}),
                "cycle": FULL_CYCLE,
                "cycle_finished": utcnow().isoformat(),
                "seconds": summary.seconds,
            }
    dict.__setitem__(summary, "seconds", summary.seconds)  # duracion por paso, para ver el mas lento
    log.info("ciclo terminado: %s", summary)
    return summary


def _guarded(engine, name: str, step) -> dict:
    """Un paso que falla no tumba el ciclo: se registra y se sigue."""
    try:
        with session_scope(engine) as session:
            return step(session)
    except Exception as exc:
        log.exception("%s: el paso fallo", name)
        return {"error": str(exc)[:300]}


def last_full_cycle(settings: Settings) -> datetime | None:
    """Fin del ultimo ciclo completo terminado. Un ciclo cortado por un redespliegue no cuenta: antes se
    contaba su inicio y, con despliegues cada pocos minutos, el ciclo se aplazaba sin terminar nunca."""
    engine = get_engine(settings.database_url)
    with session_scope(engine) as session:
        rows = session.execute(select(CrawlRun.stats).order_by(CrawlRun.id.desc()).limit(200))
        done = next((st for (st,) in rows if (st or {}).get("cycle") == FULL_CYCLE), None)
    if done is None:
        return None
    at = datetime.fromisoformat(done["cycle_finished"])
    return at if at.tzinfo else at.replace(tzinfo=UTC)


def next_cycle_at(settings: Settings, now: datetime | None = None) -> datetime | None:
    """Siguiente ciclo completo: ultimo terminado + intervalo; None si ya toca (o nunca hubo uno)."""
    now = now or datetime.now(UTC)
    last = last_full_cycle(settings)
    if last is None:
        return None
    due = last + timedelta(minutes=settings.crawl_interval_minutes)
    return due if due > now else None


def next_breaking_at(settings: Settings, now: datetime | None = None) -> datetime:
    """Siguiente vuelta del carril rapido: fin del ultimo rastreo (de cualquier carril) + intervalo, o ya.

    Anclado a la base como el ciclo completo: con redespliegues cada pocos minutos, un temporizador que
    empieza en +10 min desde el arranque no llegaba a dispararse nunca (medido en produccion 2026-10-19)."""
    now = now or datetime.now(UTC)
    engine = get_engine(settings.database_url)
    with session_scope(engine) as session:
        last = session.scalar(
            select(CrawlRun.finished_at).where(CrawlRun.finished_at.is_not(None)).order_by(CrawlRun.id.desc())
        )
    if last is None:
        return now
    last = last if last.tzinfo else last.replace(tzinfo=UTC)
    return max(now, last + timedelta(minutes=settings.breaking_interval_minutes))


def add_jobs(
    scheduler, settings: Settings, first_cycle: datetime | None = None, first_breaking: datetime | None = None
) -> None:
    """Ciclo completo cada crawl_interval_minutes (el primero en `first_cycle`, si se da) y carril de
    ultimo minuto cada breaking_interval_minutes (el primero en `first_breaking`, si se da)."""
    extra = {"next_run_time": first_cycle} if first_cycle else {}
    scheduler.add_job(
        run_cycle,
        "interval",
        minutes=settings.crawl_interval_minutes,
        args=[settings],
        id="crawl",
        max_instances=1,
        coalesce=True,
        # Nunca next_run_time=None: en APScheduler 3 eso deja el trabajo en pausa y el ciclo horario solo
        # ocurria al redesplegar. Sin `first_cycle`, el primero cae a +intervalo.
        **extra,
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
            misfire_grace_time=120,  # "ya" se calcula antes de start(): que no se pierda por milisegundos
            **({"next_run_time": first_breaking} if first_breaking else {}),
        )


def main(settings: Settings | None = None) -> None:  # pragma: no cover - bucle infinito
    settings = settings or get_settings()
    scheduler = BlockingScheduler(timezone="UTC")
    due = next_cycle_at(settings)
    if due:
        log.info("worker: el ultimo ciclo completo es reciente; el siguiente, a las %s", f"{due:%H:%M} UTC")
    else:
        log.info("worker: toca ciclo completo ya, despues cada %s min", settings.crawl_interval_minutes)
        try:
            run_cycle(settings)
        except Exception:
            log.exception("el primer ciclo fallo; el planificador lo reintentara")
    # El carril rapido se calcula despues del ciclo del arranque: si ese ciclo acaba de rastrear, espera.
    breaking = next_breaking_at(settings) if settings.breaking_interval_minutes > 0 else None
    add_jobs(scheduler, settings, first_cycle=due, first_breaking=breaking)
    if breaking:
        log.info("worker: ultimo minuto, siguiente vuelta a las %s", f"{breaking:%H:%M} UTC")
    scheduler.start()
