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
    summary = worker.run_cycle()
    assert summary["articles_new"] == 0
    get_engine.cache_clear()


def test_database_url_normalization(monkeypatch):
    from truthnews.config import get_settings

    monkeypatch.setenv("DATABASE_URL", "postgres://u:p@h/db")
    assert get_settings().database_url == "postgresql+psycopg://u:p@h/db"
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    assert get_settings().database_url == "postgresql+psycopg://u:p@h/db"
    monkeypatch.setenv("FETCH_FULL_TEXT", "no")
    assert get_settings().fetch_full_text is False
