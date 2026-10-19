"""Medida en vivo de programas y promesas (ADR 0037) sobre una base SQLite temporal.

Descubre los programas de todos los partidos del registro (robots.txt respetado) e importa los de unas
elecciones (por defecto, generales de 2023). Uso: python tools/measure_programas.py [tipo] [ano]
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select

from truthnews.config import get_settings
from truthnews.crawler.http import PoliteClient
from truthnews.db import make_engine, session_scope
from truthnews.elections import programs as pg
from truthnews.migrate import upgrade
from truthnews.models import Program, Promise
from truthnews.registry import load_political


def main(kind: str = "generales", year: int = 2023) -> dict:
    url = f"sqlite:///{Path(tempfile.mkdtemp()) / 'm.db'}"
    upgrade(url)
    engine = make_engine(url)
    settings = get_settings()
    now = datetime.now(UTC)
    out: dict = {"measured_at": now.isoformat(timespec="seconds"), "parties": {}}

    async def go(session):
        async with PoliteClient(settings.user_agent, per_domain_delay=1.0, timeout=90) as client:
            t0 = time.monotonic()
            for a in load_political():
                cands, why = await pg.discover(client, a)
                pg.store(session, cands, now)
                out["parties"][a.slug] = {"programs_found": len(cands), "unread": why}
            out["discovery_seconds"] = round(time.monotonic() - t0, 1)
            t0 = time.monotonic()
            for prog in session.scalars(
                select(Program).where(Program.election_kind == kind, Program.election_year == year)
            ).all():
                await pg.import_one(client, session, prog, now)
                session.flush()
                n = session.query(Promise).filter(Promise.program_id == prog.id).count()
                rows = session.scalars(select(Promise).where(Promise.program_id == prog.id))
                topics = Counter(p.topic for p in rows)
                out["parties"][prog.actor].setdefault("imported", []).append(
                    {"title": prog.title, "url": prog.url, "status": prog.status, "pages": prog.n_pages,
                     "promises": n, "with_topic": n - topics.get(None, 0), "note": prog.note}
                )
            out["import_seconds"] = round(time.monotonic() - t0, 1)

    with session_scope(engine) as session:
        asyncio.run(go(session))
        out["programs_total"] = session.query(Program).count()
        out["promises_total"] = session.query(Promise).count()
    out["parties_with_programs"] = sum(1 for p in out["parties"].values() if p["programs_found"])
    out["parties_unreadable"] = sorted(s for s, p in out["parties"].items() if p["unread"])
    return out


if __name__ == "__main__":
    args = sys.argv[1:]
    kind = args[0] if args else "generales"
    year = int(args[1]) if len(args) > 1 else 2023
    print(json.dumps(main(kind, year), ensure_ascii=False, indent=1))
