"""Linea de comandos: `python -m truthnews <orden>`."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys

from truthnews import registry
from truthnews.config import get_settings


def _cmd_db_upgrade(_args) -> int:
    from truthnews.migrate import upgrade

    upgrade(get_settings().database_url)
    print("base de datos al dia")
    return 0


def _cmd_sources_stats(_args) -> int:
    print(json.dumps(registry.stats(), indent=2, ensure_ascii=False, default=sorted))
    return 0


def _cmd_sources_sync(_args) -> int:
    from truthnews.crawler.ingest import sync_registry
    from truthnews.db import get_engine, session_scope

    with session_scope(get_engine()) as session:
        print(json.dumps(sync_registry(session)))
    return 0


def _cmd_crawl(args) -> int:
    from dataclasses import replace

    from truthnews.crawler.ingest import crawl, sync_registry
    from truthnews.db import get_engine, session_scope

    settings = get_settings()
    if args.no_text:
        settings = replace(settings, fetch_full_text=False)
    engine = get_engine(settings.database_url)
    with session_scope(engine) as session:
        sync_registry(session)
    with session_scope(engine) as session:
        run = asyncio.run(crawl(session, settings, outlet_slugs=args.outlet or None))
        out = {
            "run": run.id,
            "feeds_total": run.feeds_total,
            "feeds_ok": run.feeds_ok,
            "feeds_failed": run.feeds_failed,
            "articles_new": run.articles_new,
            "robots_blocked": run.robots_blocked,
            **run.stats,
            "seconds": round((run.finished_at - run.started_at).total_seconds(), 1),
        }
    print(json.dumps(out, indent=2))
    return 0


def _cmd_analyze(args) -> int:
    from datetime import timedelta

    from truthnews.analysis.pipeline import run
    from truthnews.db import get_engine, session_scope
    from truthnews.models import utcnow

    with session_scope(get_engine()) as session:
        out = run(session, since=utcnow() - timedelta(hours=args.hours))
    print(json.dumps(out, indent=2))
    return 0


def _cmd_serve(args) -> int:  # pragma: no cover - arranca un servidor
    import uvicorn

    uvicorn.run(
        "truthnews.web.app:create_app",
        factory=True,
        host=args.host,
        port=int(os.environ.get("PORT", args.port)),
        proxy_headers=True,
        forwarded_allow_ips="*",
    )
    return 0


def _cmd_worker(_args) -> int:  # pragma: no cover - bucle infinito
    from truthnews.worker import main as worker_main

    worker_main()
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="truthnews")
    sub = p.add_subparsers(dest="cmd", required=True)
    db = sub.add_parser("db").add_subparsers(dest="sub", required=True)
    db.add_parser("upgrade").set_defaults(func=_cmd_db_upgrade)
    src = sub.add_parser("sources").add_subparsers(dest="sub", required=True)
    src.add_parser("stats").set_defaults(func=_cmd_sources_stats)
    src.add_parser("sync").set_defaults(func=_cmd_sources_sync)
    c = sub.add_parser("crawl")
    c.add_argument("--outlet", action="append", help="limitar a uno o varios slugs")
    c.add_argument("--no-text", action="store_true", help="no descargar el texto completo")
    c.set_defaults(func=_cmd_crawl)
    an = sub.add_parser("analyze", help="agrupa en historias y verifica afirmaciones")
    an.add_argument(
        "--hours", type=int, default=72, help="verificar articulos ingeridos en las ultimas N horas"
    )
    an.set_defaults(func=_cmd_analyze)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", default=8000, type=int)
    s.set_defaults(func=_cmd_serve)
    sub.add_parser("worker").set_defaults(func=_cmd_worker)
    return p


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        stream=sys.stdout,  # Railway marca stderr como error
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("trafilatura").setLevel(logging.ERROR)
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
