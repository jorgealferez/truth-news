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


def _cmd_entities(args) -> int:
    from truthnews.db import get_engine, session_scope
    from truthnews.entities.store import process

    with session_scope(get_engine()) as session:
        out = process(session, limit=args.limit)
    print(json.dumps(out, indent=2))
    return 0


def _cmd_archive(args) -> int:
    from truthnews import archive
    from truthnews.db import get_engine, session_scope

    with session_scope(get_engine()) as session:
        out = archive.run(session, budget=args.queries, max_seconds=args.max_seconds)
    print(json.dumps(out, indent=2, default=str))
    return 0


def _cmd_social(args) -> int:
    """`social preview`: las piezas que saldrian ahora, por red, sin escribir nada. `social run`: el paso
    del worker (con `--dry`, en modo prueba aunque haya credenciales)."""
    from dataclasses import replace

    from truthnews.db import get_engine, session_scope
    from truthnews.social import queue
    from truthnews.social.compose import LIMITS, fit, length
    from truthnews.social.config import SocialSettings
    from truthnews.social.select import candidates

    settings, social = get_settings(), SocialSettings()
    with session_scope(get_engine(settings.database_url)) as session:
        if args.sub == "run":
            out = queue.run(
                session,
                settings.site_url,
                replace(social, dry_run=social.dry_run or args.dry),
                lang=settings.default_language,
            )
            print(json.dumps(out, indent=2, ensure_ascii=False))
            return 0
        found = candidates(
            session, settings.site_url, social.min_score, social.window_hours, settings.default_language
        )
        for c in found[: args.limit]:
            print(f"== {c.kind} {c.ref_id} (relevancia {c.score:.2f})")
            for network in LIMITS:
                text = fit(network, c.draft)
                print(f"-- {network} ({length(network, text)}/{LIMITS[network][0]})\n{text}")
        print(f"{len(found)} candidatas")
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


def _cmd_lookup(args) -> int:
    """Consulta puntual de interes publico (ADR 0029): imprime la traza para la evidencia, en JSON."""
    import re

    from truthnews.crawler.targeted import lookup

    doc, hop = re.compile(args.documento), re.compile(args.siguiente) if args.siguiente else None
    rec = asyncio.run(
        lookup(
            args.url,
            is_document=lambda url, text: bool(doc.search(text)),
            next_hop=(lambda links: next((u for u in links if hop.search(u)), None)) if hop else None,
            reason=args.motivo,
            justification=args.justificacion,
            claim=args.afirmacion,
            alternatives_tried=args.alternativa or [],
            user_agent=get_settings().user_agent,
        )
    )
    print(json.dumps(rec.as_payload(), ensure_ascii=False, indent=2))
    return 0 if rec.document_url else 1


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
    en = sub.add_parser("entities", help="extrae personas y entidades de las noticias pendientes")
    en.add_argument("--limit", type=int, default=2000)
    en.set_defaults(func=_cmd_entities)
    ar = sub.add_parser("archive", help="importa noticias antiguas de las entidades (GDELT)")
    ar.add_argument("--queries", type=int, default=6)
    ar.add_argument("--max-seconds", type=float, default=90.0)
    ar.set_defaults(func=_cmd_archive)
    so = sub.add_parser("social", help="redes: vista previa o paso del worker").add_subparsers(
        dest="sub", required=True
    )
    pv = so.add_parser("preview", help="piezas que saldrian ahora, sin escribir nada")
    pv.add_argument("--limit", type=int, default=5)
    pv.set_defaults(func=_cmd_social)
    sr = so.add_parser("run", help="el paso de redes del worker")
    sr.add_argument("--dry", action="store_true", help="modo prueba aunque haya credenciales")
    sr.set_defaults(func=_cmd_social)
    s = sub.add_parser("serve")
    s.add_argument("--host", default="0.0.0.0")
    s.add_argument("--port", default=8000, type=int)
    s.set_defaults(func=_cmd_serve)
    sub.add_parser("worker").set_defaults(func=_cmd_worker)
    lk = sub.add_parser("consulta-puntual", help="documento concreto para contrastar un dato (ADR 0029)")
    lk.add_argument("url")
    lk.add_argument("--documento", required=True, help="regex que identifica el documento buscado")
    lk.add_argument("--siguiente", help="regex de los enlaces que acercan al documento")
    lk.add_argument("--motivo", required=True)
    lk.add_argument("--justificacion", required=True, choices=["dudas-entre-medios", "falta-de-pruebas"])
    lk.add_argument("--afirmacion", required=True)
    lk.add_argument("--alternativa", action="append", help="via alternativa ya probada (repetible)")
    lk.set_defaults(func=_cmd_lookup)
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
