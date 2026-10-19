import json

from truthnews import cli, worker
from truthnews.db import get_engine


def test_sources_stats(capsys):
    assert cli.main(["sources", "stats"]) == 0
    assert json.loads(capsys.readouterr().out)["by_country"]["ES"] >= 80


def test_db_upgrade_sync_and_crawl(tmp_path, monkeypatch, capsys):
    url = f"sqlite:///{tmp_path / 'cli.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    get_engine.cache_clear()
    assert cli.main(["db", "upgrade"]) == 0
    assert cli.main(["sources", "sync"]) == 0
    assert '"created"' in capsys.readouterr().out

    async def fake_crawl(session, settings, transport=None, outlet_slugs=None):
        from truthnews.models import CrawlRun, utcnow

        assert settings.fetch_full_text is False and outlet_slugs == ["el-pais"]
        run = CrawlRun(finished_at=utcnow(), stats={"outlets": 1})
        session.add(run)
        session.flush()
        return run

    monkeypatch.setattr("truthnews.crawler.ingest.crawl", fake_crawl)
    assert cli.main(["crawl", "--no-text", "--outlet", "el-pais"]) == 0
    assert json.loads(capsys.readouterr().out)["outlets"] == 1

    monkeypatch.setattr(
        worker,
        "crawl",
        lambda s, st: fake_crawl(s, st.__class__(fetch_full_text=False), outlet_slugs=["el-pais"]),
    )
    monkeypatch.setattr(worker, "process_pending", lambda session, ai=None: {"processed": 0, "failed": 0})
    monkeypatch.setattr(worker.political, "run", lambda session, settings: {"channels": 0})
    summary = worker.run_cycle()
    assert summary["political"] == {"channels": 0}
    assert summary["articles_new"] == 0
    assert summary["investigations"] == {"processed": 0, "failed": 0}
    get_engine.cache_clear()


def test_database_url_normalization(monkeypatch):
    from truthnews.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    assert get_settings().database_url == "postgresql+psycopg://u:p@h/db"
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    assert get_settings().database_url == "postgresql+psycopg://u:p@h/db"
    monkeypatch.setenv("FETCH_FULL_TEXT", "no")
    assert get_settings().fetch_full_text is False


def test_recent_cycle_skips_duplicate_runs_after_redeploys(tmp_path, monkeypatch):
    from datetime import UTC, datetime, timedelta

    from truthnews.config import Settings
    from truthnews.db import session_scope
    from truthnews.migrate import upgrade
    from truthnews.models import CrawlRun

    url = f"sqlite:///{tmp_path / 'w.db'}"
    upgrade(url)
    get_engine.cache_clear()
    settings = Settings(database_url=url)
    assert worker.recent_cycle(settings) is False
    with session_scope(get_engine(url)) as s:
        s.add(CrawlRun(started_at=datetime.now(UTC) - timedelta(minutes=10)))
    assert worker.recent_cycle(settings) is True
    assert worker.recent_cycle(settings, now=datetime.now(UTC) + timedelta(minutes=30)) is False
    get_engine.cache_clear()


def test_breaking_lane_crawls_national_outlets_and_never_overlaps(tmp_path, monkeypatch):
    """Ultimo minuto (peticion 2026-10-19): medios nacionales cada pocos minutos, sin IA ni solaparse."""
    from datetime import UTC, datetime, timedelta

    from apscheduler.schedulers.background import BackgroundScheduler

    from truthnews.config import Settings
    from truthnews.db import session_scope
    from truthnews.migrate import upgrade
    from truthnews.models import CrawlRun, Outlet, utcnow

    url = f"sqlite:///{tmp_path / 'b.db'}"
    upgrade(url)
    get_engine.cache_clear()
    settings = Settings(database_url=url)
    assert worker.run_breaking(settings) is None  # sin medios nacionales no hay nada que rastrear
    with session_scope(get_engine(url)) as s:
        for slug, scope, country in [
            ("nac", "national", "ES"),
            ("loc", "local", "ES"),
            ("fr", "national", "FR"),
        ]:
            s.add(
                Outlet(
                    slug=slug, name=slug, homepage="https://x", country=country, language="es", scope=scope
                )
            )
    seen = {}

    async def fake_crawl(session, st, transport=None, outlet_slugs=None):
        seen["slugs"] = outlet_slugs
        run = CrawlRun(finished_at=utcnow(), stats={"outlets": 1})
        session.add(run)
        session.flush()
        return run

    monkeypatch.setattr(worker, "crawl", fake_crawl)
    summary = worker.run_breaking(settings)
    assert seen["slugs"] == ["nac"] and summary["lane"] == "rapido" and "analysis" in summary
    # Un rastreo del carril rapido no cuenta como ciclo completo tras un redespliegue.
    assert worker.recent_cycle(settings) is False
    with session_scope(get_engine(url)) as s:
        s.add(CrawlRun(started_at=datetime.now(UTC) - timedelta(minutes=5)))
    assert worker.recent_cycle(settings) is True

    # Con el ciclo completo en marcha, el carril rapido se salta la vuelta.
    with worker._busy:
        assert worker.run_breaking(settings) is None

    # Los dos trabajos quedan programados (antes, next_run_time=None dejaba el horario en pausa).
    sched = BackgroundScheduler(timezone="UTC")
    worker.add_jobs(sched, settings)
    sched.start(paused=True)
    try:
        jobs = {j.id: j for j in sched.get_jobs()}
        assert set(jobs) == {"crawl", "breaking"} and all(j.next_run_time for j in jobs.values())
    finally:
        sched.shutdown(wait=False)
    sched = BackgroundScheduler(timezone="UTC")
    worker.add_jobs(sched, Settings(database_url=url, breaking_interval_minutes=0))
    assert [j.id for j in sched.get_jobs()] == ["crawl"]
    get_engine.cache_clear()
