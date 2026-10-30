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
    # Relecturas por ciclo del texto completo para ver si un medio cambio una cifra (ADR 0052).
    max_text_recheck_per_run: int = field(
        default_factory=lambda: int(os.environ.get("MAX_TEXT_RECHECK_PER_RUN", "60"))
    )
    # IA (ADR 0007). Sin ANTHROPIC_API_KEY no se generan temas ni piezas; el resto funciona igual.
    ai_enabled: bool = field(default_factory=lambda: bool(os.environ.get("ANTHROPIC_API_KEY")))
    ai_model: str = field(default_factory=lambda: os.environ.get("AI_MODEL", "claude-opus-5-5"))
    ai_effort: str = field(default_factory=lambda: os.environ.get("AI_EFFORT", "high"))
    ai_max_pieces_per_cycle: int = field(
        default_factory=lambda: int(os.environ.get("AI_MAX_PIECES_PER_CYCLE", "6"))
    )
    ai_piece_concurrency: int = field(  # llamadas de piezas a la vez; 1 = en serie
        default_factory=lambda: int(os.environ.get("AI_PIECE_CONCURRENCY", "1"))
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
    # Coste de la IA (ADR 0054). Un tema con pieza reciente no se reescribe hasta pasados estos minutos aunque
    # haya entrado un articulo nuevo (antes: 6 piezas Opus en cada ciclo); un tema sin pieza se escribe ya.
    ai_piece_refresh_minutes: int = field(
        default_factory=lambda: int(os.environ.get("AI_PIECE_REFRESH_MINUTES", "120"))
    )
    # Tope de gasto de IA por dia UTC, en USD; al llegar, los pasos de IA se saltan hasta el dia siguiente.
    # 0 = sin tope. Decision del usuario 2026-10-30: 2 EUR al dia en total (general 1,5 + verificacion 0,2 +
    # foco 0, que gasta de la general), con margen para la ultima llamada antes del tope.
    ai_daily_budget_usd: float = field(
        default_factory=lambda: float(os.environ.get("AI_DAILY_BUDGET_USD", "1.5"))
    )
    # Bolsa aparte para juzgar afirmaciones (decision del usuario 2026-10-19): agotar el tope general no para
    # las verificaciones. 0 = sin bolsa propia (las verificaciones gastan del tope general).
    ai_daily_budget_verify_usd: float = field(
        default_factory=lambda: float(os.environ.get("AI_DAILY_BUDGET_VERIFY_USD", "0.2"))
    )
    # Foco (ADR 0056): interruptor para un suceso grave. AI_FOCUS lleva los terminos separados por comas; lo
    # que case pasa primero por piezas, hilos, afirmaciones e investigacion, con bolsa y cadencia propias.
    ai_focus: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            t.strip() for t in os.environ.get("AI_FOCUS", "").split(",") if t.strip()
        )
    )
    ai_focus_question: str = field(default_factory=lambda: os.environ.get("AI_FOCUS_QUESTION", ""))
    ai_focus_budget_usd: float = field(  # bolsa diaria del foco; 0 = gasta de la general
        default_factory=lambda: float(os.environ.get("AI_FOCUS_BUDGET_USD", "0"))
    )
    ai_focus_max_pieces: int = field(default_factory=lambda: int(os.environ.get("AI_FOCUS_MAX_PIECES", "3")))
    ai_focus_max_threads: int = field(
        default_factory=lambda: int(os.environ.get("AI_FOCUS_MAX_THREADS", "2"))
    )
    ai_focus_claims_calls: int = field(
        default_factory=lambda: int(os.environ.get("AI_FOCUS_CLAIMS_CALLS", "4"))
    )
    ai_focus_refresh_minutes: int = field(
        default_factory=lambda: int(os.environ.get("AI_FOCUS_REFRESH_MINUTES", "30"))
    )
    # Publicidad (cliente de ads-service, microservices-ecosystem). Sin URL o sin clave no se pinta nada.
    ads_service_url: str = field(default_factory=lambda: os.environ.get("ADS_SERVICE_URL", ""))
    ads_site_key: str = field(default_factory=lambda: os.environ.get("ADS_SITE_KEY", ""))
    # Publicidad propia de Ridelta por zona (ADR 0055): rellena los huecos que ads-service deja vacios.
    house_ads_enabled: bool = field(default_factory=lambda: os.environ.get("HOUSE_ADS_ENABLED", "1") == "1")
    # Extraccion de afirmaciones con IA (ADR 0019): llamadas de 40 frases por ciclo y esfuerzo propio.
    ai_claims_max_calls: int = field(default_factory=lambda: int(os.environ.get("AI_CLAIMS_MAX_CALLS", "3")))
    ai_claims_effort: str = field(default_factory=lambda: os.environ.get("AI_CLAIMS_EFFORT", "medium"))
    # Declaraciones de los partidos con IA (ADR 0031): llamadas por ciclo; 0 la apaga.
    statement_ai_max_calls: int = field(
        default_factory=lambda: int(os.environ.get("STATEMENT_AI_MAX_CALLS", "2"))
    )
    # Dias de BOE (nombramientos y ceses) que la web guarda en memoria para confirmar noticias; 0 = nada.
    boe_index_days: int = field(default_factory=lambda: int(os.environ.get("BOE_INDEX_DAYS", "30")))
    # Elecciones (ADR 0036): dias de BOE en los que la web busca convocatorias; 0 = solo el registro.
    elections_lookback_days: int = field(
        default_factory=lambda: int(os.environ.get("ELECTIONS_LOOKBACK_DAYS", "75"))
    )
    # Programas electorales (ADR 0037): descubrir e importar en las webs de los partidos; 0 = apagado.
    programs_enabled: bool = field(default_factory=lambda: os.environ.get("PROGRAMS_ENABLED", "1") == "1")
    # Cumplimiento de promesas (18c, ADR 0040): promesas revisadas por las reglas en cada ciclo (BOE y datos)
    # y, de lo que el codigo no decide, como mucho N llamadas de IA por ciclo con lotes de M promesas.
    promises_check_per_run: int = field(
        default_factory=lambda: int(os.environ.get("PROMISES_CHECK_PER_RUN", "20"))
    )
    promises_ai_max_calls: int = field(
        default_factory=lambda: int(os.environ.get("PROMISES_AI_MAX_CALLS", "2"))
    )
    promises_ai_batch: int = field(default_factory=lambda: int(os.environ.get("PROMISES_AI_BATCH", "10")))
    promises_ai_effort: str = field(default_factory=lambda: os.environ.get("PROMISES_AI_EFFORT", "low"))
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
