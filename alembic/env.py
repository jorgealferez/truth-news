"""Entorno de Alembic: la URL sale de DATABASE_URL (o de la configuracion pasada por codigo)."""

from __future__ import annotations

from sqlalchemy import engine_from_config, pool, text

from alembic import context
from truthnews.config import get_settings
from truthnews.models import Base

config = context.config
if not config.get_main_option("sqlalchemy.url"):
    config.set_main_option("sqlalchemy.url", get_settings().database_url)
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"), target_metadata=target_metadata, literal_binds=True
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}), prefix="sqlalchemy.", poolclass=pool.NullPool
    )
    with connectable.connect() as connection:
        if connection.dialect.name == "postgresql":
            # web y worker arrancan a la vez y ambos migran: el bloqueo consultivo serializa las migraciones.
            connection.execute(text("SELECT pg_advisory_lock(727274)"))
            connection.commit()
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=connection.dialect.name == "sqlite",
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
