"""Configuracion por variables de entorno (12-factor). Sin valores secretos por defecto."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "si", "on"}


def _database_url() -> str:
    url = os.environ.get("DATABASE_URL", "sqlite:///./truthnews.db")
    # Railway y Heroku entregan postgres://; SQLAlchemy 2 + psycopg 3 necesita el dialecto explicito.
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://") :]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=_database_url)
    site_name: str = field(default_factory=lambda: os.environ.get("SITE_NAME", "Truth News"))
    site_url: str = field(default_factory=lambda: os.environ.get("SITE_URL", "http://localhost:8000"))
    default_language: str = field(default_factory=lambda: os.environ.get("DEFAULT_LANGUAGE", "es"))
    default_country: str = field(default_factory=lambda: os.environ.get("DEFAULT_COUNTRY", "ES"))
    user_agent: str = field(
        default_factory=lambda: os.environ.get(
            "CRAWLER_USER_AGENT",
            "TruthNewsBot/0.1 (+https://github.com/jorgealferez/truth-news; verificacion de noticias)",
        )
    )
    crawl_interval_minutes: int = field(
        default_factory=lambda: int(os.environ.get("CRAWL_INTERVAL_MINUTES", "60"))
    )
    crawl_concurrency: int = field(default_factory=lambda: int(os.environ.get("CRAWL_CONCURRENCY", "16")))
    per_domain_delay_seconds: float = field(
        default_factory=lambda: float(os.environ.get("PER_DOMAIN_DELAY_SECONDS", "1.0"))
    )
    fetch_full_text: bool = field(default_factory=lambda: _bool("FETCH_FULL_TEXT", True))
    max_articles_per_feed: int = field(
        default_factory=lambda: int(os.environ.get("MAX_ARTICLES_PER_FEED", "30"))
    )
    # Tope de textos completos por rastreo (los mas recientes primero) para acotar la duracion del ciclo.
    max_text_fetch_per_run: int = field(
        default_factory=lambda: int(os.environ.get("MAX_TEXT_FETCH_PER_RUN", "600"))
    )
    admin_user: str = field(default_factory=lambda: os.environ.get("ADMIN_USER", "admin"))
    admin_password: str = field(default_factory=lambda: os.environ.get("ADMIN_PASSWORD", ""))
    role: str = field(default_factory=lambda: os.environ.get("TRUTHNEWS_ROLE", "web"))


def get_settings() -> Settings:
    return Settings()
