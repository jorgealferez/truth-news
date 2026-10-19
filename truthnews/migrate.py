"""Aplicar migraciones Alembic desde codigo (arranque de web/worker y tests)."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config

from alembic import command

ROOT = Path(__file__).resolve().parent.parent


def alembic_config(url: str) -> Config:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.replace("%", "%%"))
    return cfg


def upgrade(url: str, revision: str = "heads") -> None:
    # "heads" y no "head": si dos agentes dejan por error dos ramas de migracion, el arranque las aplica
    # en vez de tumbar web y worker. La rama doble se detecta antes en el gauntlet (test de un solo head).
    command.upgrade(alembic_config(url), revision)


def downgrade(url: str, revision: str = "base") -> None:
    command.downgrade(alembic_config(url), revision)
