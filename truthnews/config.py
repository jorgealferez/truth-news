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
    site_name: str = field(default_factory=lambda: os.environ.get("SITE_NAME", "NosMienten"))
    site_url: str = field(default_factory=lambda: os.environ.get("SITE_URL", "http://localhost:8000"))
    site_domain: str = field(default_factory=lambda: os.environ.get("SITE_DOMAIN", "nosmienten.com"))
    default_language: str = field(default_factory=lambda: os.environ.get("DEFAULT_LANGUAGE", "es"))
    default_country: str = field(default_factory=lambda: os.environ.get("DEFAULT_COUNTRY", "ES"))
    # Idiomas que se ofrecen a buscadores (hreflang, sitemap, index). Los demas se sirven con noindex
    # mientras su contenido siga sin traducir (decision del usuario 2026-10-19).
    indexed_languages: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            x.strip() for x in os.environ.get("INDEXED_LANGUAGES", "es").split(",") if x.strip()
        )
    )
    user_agent: str = field(
        default_factory=lambda: os.environ.get(
            "CRAWLER_USER_AGENT",
            "TruthNewsBot/0.1 (+https://github.com/jorgealferez/truth-news; verificacion de noticias)",
        )
    )
    crawl_interval_minutes: int = field(
        default_factory=lambda: int(os.environ.get("CRAWL_INTERVAL_MINUTES", "60"))
    )
    # Carril rapido de ultimo minuto: medios nacionales y agencias del pais por defecto, sin IA, cada N
    # minutos ademas del ciclo completo (peticion del usuario 2026-10-19). 0 lo desactiva.
    breaking_interval_minutes: int = field(
        default_factory=lambda: int(os.environ.get("BREAKING_INTERVAL_MINUTES", "10"))
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
    # Relleno por ciclo del texto de articulos recientes de politica y economia que no lo tienen.
    max_text_backfill_per_run: int = field(
        default_factory=lambda: int(os.environ.get("MAX_TEXT_BACKFILL_PER_RUN", "150"))
    )
    # IA (ADR 0007). Sin ANTHROPIC_API_KEY no se generan temas ni piezas; el resto funciona igual.
    ai_enabled: bool = field(default_factory=lambda: bool(os.environ.get("ANTHROPIC_API_KEY")))
    ai_model: str = field(default_factory=lambda: os.environ.get("AI_MODEL", "claude-opus-5-5"))
    ai_effort: str = field(default_factory=lambda: os.environ.get("AI_EFFORT", "high"))
    ai_max_pieces_per_cycle: int = field(
        default_factory=lambda: int(os.environ.get("AI_MAX_PIECES_PER_CYCLE", "6"))
    )
    ai_piece_concurrency: int = field(  # llamadas de piezas a la vez; 1 = en serie
        default_factory=lambda: int(os.environ.get("AI_PIECE_CONCURRENCY", "3"))
    )
    ai_max_threads_per_cycle: int = field(
        default_factory=lambda: int(os.environ.get("AI_MAX_THREADS_PER_CYCLE", "2"))
    )
    ai_max_translations_per_cycle: int = field(
        default_factory=lambda: int(os.environ.get("AI_MAX_TRANSLATIONS_PER_CYCLE", "120"))
    )
    ai_max_translations_en_per_cycle: int = field(
        default_factory=lambda: int(os.environ.get("AI_MAX_TRANSLATIONS_EN_PER_CYCLE", "60"))
    )
    # Publicidad (cliente de ads-service, microservices-ecosystem). Sin URL o sin clave no se pinta nada.
    ads_service_url: str = field(default_factory=lambda: os.environ.get("ADS_SERVICE_URL", ""))
    ads_site_key: str = field(default_factory=lambda: os.environ.get("ADS_SITE_KEY", ""))
    # Extraccion de afirmaciones con IA (ADR 0019): llamadas de 40 frases por ciclo y esfuerzo propio.
    ai_claims_max_calls: int = field(default_factory=lambda: int(os.environ.get("AI_CLAIMS_MAX_CALLS", "3")))
    ai_claims_effort: str = field(default_factory=lambda: os.environ.get("AI_CLAIMS_EFFORT", "medium"))
    # Dias de BOE (nombramientos y ceses) que la web guarda en memoria para confirmar noticias; 0 = nada.
    boe_index_days: int = field(default_factory=lambda: int(os.environ.get("BOE_INDEX_DAYS", "30")))
    # Elecciones (ADR 0036): dias de BOE en los que la web busca convocatorias; 0 = solo el registro.
    elections_lookback_days: int = field(
        default_factory=lambda: int(os.environ.get("ELECTIONS_LOOKBACK_DAYS", "75"))
    )
    # Programas electorales (ADR 0037): descubrir e importar en las webs de los partidos; 0 = apagado.
    programs_enabled: bool = field(default_factory=lambda: os.environ.get("PROGRAMS_ENABLED", "1") == "1")
    # Entidades y archivo (ADR 0028/0030): noticias por tanda; tramos GKG de 15 min por ciclo (0 = apagado),
    # cada cuanto se toma un tramo hacia atras y de que paises son los medios que se importan.
    entities_batch: int = field(default_factory=lambda: int(os.environ.get("ENTITIES_BATCH", "2000")))
    archive_slots_per_cycle: int = field(
        default_factory=lambda: int(os.environ.get("ARCHIVE_SLOTS_PER_CYCLE", "2"))
    )
    archive_stride_minutes: int = field(
        default_factory=lambda: int(os.environ.get("ARCHIVE_STRIDE_MINUTES", "360"))
    )
    archive_countries: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            c.strip().upper() for c in os.environ.get("ARCHIVE_COUNTRIES", "ES").split(",") if c.strip()
        )
    )
    admin_user: str = field(default_factory=lambda: os.environ.get("ADMIN_USER", "admin"))
    admin_password: str = field(default_factory=lambda: os.environ.get("ADMIN_PASSWORD", ""))
    role: str = field(default_factory=lambda: os.environ.get("TRUTHNEWS_ROLE", "web"))
    # Datos del titular para /aviso-legal (LSSI art. 10), /privacidad (RGPD art. 13) y /transparencia
    # (Reglamento 2024/1083 art. 6). Los aporta el titular; sin ellos las paginas lo dicen, no se inventan.
    legal_owner: str = field(default_factory=lambda: os.environ.get("LEGAL_OWNER", ""))
    legal_tax_id: str = field(default_factory=lambda: os.environ.get("LEGAL_TAX_ID", ""))
    legal_address: str = field(default_factory=lambda: os.environ.get("LEGAL_ADDRESS", ""))
    legal_email: str = field(default_factory=lambda: os.environ.get("LEGAL_EMAIL", ""))
    legal_registry: str = field(default_factory=lambda: os.environ.get("LEGAL_REGISTRY", ""))
    legal_ownership: str = field(default_factory=lambda: os.environ.get("LEGAL_OWNERSHIP", ""))
    legal_state_ads: str = field(default_factory=lambda: os.environ.get("LEGAL_STATE_ADS", ""))


def get_settings() -> Settings:
    return Settings()
