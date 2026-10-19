from __future__ import annotations

import pytest

from truthnews.db import make_engine, session_scope
from truthnews.migrate import upgrade


@pytest.fixture(autouse=True)
def _no_boe_index(monkeypatch):
    """Sin descargas del BOE en segundo plano en los tests (se prueba aparte con un transporte falso)."""
    monkeypatch.setenv("BOE_INDEX_DAYS", "0")
    monkeypatch.setenv("ELECTIONS_LOOKBACK_DAYS", "0")
    monkeypatch.setenv("PROGRAMS_ENABLED", "0")


@pytest.fixture()
def db_url(tmp_path):
    url = f"sqlite:///{tmp_path / 'test.db'}"
    upgrade(url)
    return url


@pytest.fixture()
def engine(db_url):
    eng = make_engine(db_url)
    yield eng
    eng.dispose()


@pytest.fixture()
def session(engine):
    with session_scope(engine) as s:
        yield s


@pytest.fixture(autouse=True)
def _fresh_ai_meter(monkeypatch):
    """El contador de coste de la IA es global (ADR 0054): cada test empieza con uno nuevo y sin tope."""
    from truthnews.ai import cost

    monkeypatch.setattr(cost, "METER", cost.Meter())
