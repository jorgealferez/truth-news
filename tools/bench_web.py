"""Benchmark C7: latencia de la portada con N articulos (SQLite local, TestClient en proceso).

Uso: python tools/bench_web.py [--articles 10000] [--requests 60]
Imprime JSON con p50/p95/max en milisegundos.
"""

from __future__ import annotations

import argparse
import json
import statistics
import tempfile
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from truthnews.config import Settings
from truthnews.db import make_engine, session_scope
from truthnews.migrate import upgrade
from truthnews.models import Article, Outlet
from truthnews.registry import categories
from truthnews.web.app import create_app


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--articles", type=int, default=10_000)
    ap.add_argument("--requests", type=int, default=60)
    args = ap.parse_args()
    with tempfile.TemporaryDirectory() as tmp:
        url = f"sqlite:///{Path(tmp) / 'bench.db'}"
        upgrade(url)
        engine = make_engine(url)
        cats = list(categories())
        now = datetime.now(UTC)
        with session_scope(engine) as s:
            outlets = [
                Outlet(
                    slug=f"m{i}",
                    name=f"Medio {i}",
                    homepage="https://m",
                    country="ES",
                    language="es",
                    scope="national",
                )
                for i in range(100)
            ]
            s.add_all(outlets)
            s.flush()
            s.add_all(
                Article(
                    outlet_id=outlets[i % 100].id,
                    url=f"https://m/{i}",
                    url_hash=f"{i:064d}",
                    title=f"Titular de prueba numero {i}",
                    summary="Resumen " * 20,
                    published_at=now - timedelta(minutes=i),
                    language="es",
                    country="ES",
                    region=None,
                    category=cats[i % len(cats)],
                    topics=[],
                )
                for i in range(args.articles)
            )
        client = TestClient(create_app(Settings(database_url=url), engine=engine))
        client.get("/")  # calentamiento
        times = []
        for _ in range(args.requests):
            t0 = time.perf_counter()
            assert client.get("/").status_code == 200
            times.append((time.perf_counter() - t0) * 1000)
        times.sort()
        p95 = times[max(0, int(len(times) * 0.95) - 1)]
        print(
            json.dumps(
                {
                    "articles": args.articles,
                    "requests": args.requests,
                    "p50_ms": round(statistics.median(times), 1),
                    "p95_ms": round(p95, 1),
                    "max_ms": round(times[-1], 1),
                }
            )
        )
        engine.dispose()


if __name__ == "__main__":
    main()
