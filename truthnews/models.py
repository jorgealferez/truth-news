"""Modelo de datos (ADR 0002). Cada cambio de este fichero lleva su ADR `Tipo: datos`."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    JSON,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Outlet(Base):
    __tablename__ = "outlet"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    slug: Mapped[str] = mapped_column(String(80), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(200))
    homepage: Mapped[str] = mapped_column(String(500))
    country: Mapped[str] = mapped_column(String(2), index=True)
    language: Mapped[str] = mapped_column(String(8))
    scope: Mapped[str] = mapped_column(String(16))  # national | regional | local | international
    region: Mapped[str | None] = mapped_column(String(8), nullable=True, index=True)
    city: Mapped[str | None] = mapped_column(String(120), nullable=True)
    kind: Mapped[str] = mapped_column(String(32), default="press")  # press | tv | radio | agency | factcheck
    owner: Mapped[str | None] = mapped_column(String(200), nullable=True)
    active: Mapped[bool] = mapped_column(default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    feeds: Mapped[list[Feed]] = relationship(back_populates="outlet", cascade="all, delete-orphan")


class Feed(Base):
    __tablename__ = "feed"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outlet_id: Mapped[int] = mapped_column(ForeignKey("outlet.id", ondelete="CASCADE"), index=True)
    url: Mapped[str] = mapped_column(String(700), unique=True)
    category_hint: Mapped[str | None] = mapped_column(String(40), nullable=True)
    discovered: Mapped[bool] = mapped_column(default=False)
    active: Mapped[bool] = mapped_column(default=True)
    etag: Mapped[str | None] = mapped_column(String(300), nullable=True)
    last_modified: Mapped[str | None] = mapped_column(String(100), nullable=True)
    last_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    last_error: Mapped[str | None] = mapped_column(String(500), nullable=True)

    outlet: Mapped[Outlet] = relationship(back_populates="feeds")


class Article(Base):
    __tablename__ = "article"
    __table_args__ = (
        Index("ix_article_category_published", "category", "published_at"),
        Index("ix_article_country_published", "country", "published_at"),
        Index("ix_article_outlet_published", "outlet_id", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    outlet_id: Mapped[int] = mapped_column(ForeignKey("outlet.id", ondelete="CASCADE"))
    feed_id: Mapped[int | None] = mapped_column(ForeignKey("feed.id", ondelete="SET NULL"), nullable=True)
    url: Mapped[str] = mapped_column(String(1000))
    url_hash: Mapped[str] = mapped_column(String(64), unique=True)
    title: Mapped[str] = mapped_column(String(600))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    author: Mapped[str | None] = mapped_column(String(300), nullable=True)
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    published_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    language: Mapped[str] = mapped_column(String(8))
    country: Mapped[str] = mapped_column(String(2))
    region: Mapped[str | None] = mapped_column(String(8), nullable=True)
    category: Mapped[str] = mapped_column(String(40))
    topics: Mapped[list] = mapped_column(JSON, default=list)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    word_count: Mapped[int] = mapped_column(Integer, default=0)
    story_id: Mapped[int | None] = mapped_column(
        ForeignKey("story.id", ondelete="SET NULL", name="fk_article_story_id"), nullable=True, index=True
    )

    outlet: Mapped[Outlet] = relationship()
    story: Mapped[Story | None] = relationship(back_populates="articles")
    revisions: Mapped[list[ArticleRevision]] = relationship(
        back_populates="article", order_by="ArticleRevision.detected_at", cascade="all, delete-orphan"
    )


REVISION_FIELDS = ("title", "summary")
REVISION_MAX_CHARS = 600  # lo mismo que ya se publica del extracto (derecho de cita, ADR 0003)


class ArticleRevision(Base):
    """Un cambio de titular o extracto detectado entre dos rastreos (ADR 0015)."""

    __tablename__ = "article_revision"
    __table_args__ = (
        CheckConstraint(f"field IN {REVISION_FIELDS!r}", name="ck_article_revision_field"),
        Index("ix_article_revision_article_detected", "article_id", "detected_at"),
        Index("ix_article_revision_outlet_detected", "outlet_id", "detected_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("article.id", ondelete="CASCADE", name="fk_article_revision_article_id")
    )
    outlet_id: Mapped[int] = mapped_column(
        ForeignKey("outlet.id", ondelete="CASCADE", name="fk_article_revision_outlet_id")
    )
    crawl_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("crawl_run.id", ondelete="SET NULL", name="fk_article_revision_crawl_run_id"),
        nullable=True,
    )
    field: Mapped[str] = mapped_column(String(16))
    before: Mapped[str] = mapped_column(Text)
    after: Mapped[str] = mapped_column(Text)
    before_hash: Mapped[str] = mapped_column(String(64))
    after_hash: Mapped[str] = mapped_column(String(64))
    detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article: Mapped[Article] = relationship(back_populates="revisions")


class ArticleTranslation(Base):
    """Titular traducido con IA a un idioma de la interfaz; el original no se toca (ADR 0017)."""

    __tablename__ = "article_translation"
    __table_args__ = (UniqueConstraint("article_id", "lang", name="uq_article_translation_article_lang"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(
        ForeignKey("article.id", ondelete="CASCADE", name="fk_article_translation_article_id")
    )
    lang: Mapped[str] = mapped_column(String(8))
    title: Mapped[str] = mapped_column(String(600))
    model: Mapped[str] = mapped_column(String(80))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CrawlRun(Base):
    __tablename__ = "crawl_run"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    feeds_total: Mapped[int] = mapped_column(Integer, default=0)
    feeds_ok: Mapped[int] = mapped_column(Integer, default=0)
    feeds_failed: Mapped[int] = mapped_column(Integer, default=0)
    articles_new: Mapped[int] = mapped_column(Integer, default=0)
    robots_blocked: Mapped[int] = mapped_column(Integer, default=0)
    stats: Mapped[dict] = mapped_column(JSON, default=dict)


VERDICTS = ("verdadero", "impreciso", "falso", "enganoso", "sin-datos")


class Story(Base):
    """La misma noticia contada por uno o varios medios (ADR 0004/0005)."""

    __tablename__ = "story"
    __table_args__ = (
        Index("ix_story_country_last_seen", "country", "last_seen"),
        Index("ix_story_country_priority", "country", "priority"),
        Index("ix_story_country_relaunched", "country", "relaunched_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(600))
    category: Mapped[str] = mapped_column(String(40))
    country: Mapped[str] = mapped_column(String(2))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    n_articles: Mapped[int] = mapped_column(Integer, default=1)
    n_outlets: Mapped[int] = mapped_column(Integer, default=1)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    topic_id: Mapped[int | None] = mapped_column(
        ForeignKey("topic.id", ondelete="SET NULL", name="fk_story_topic_id"), nullable=True, index=True
    )
    # Contraste y relanzamiento (ADR 0012): se recalculan en cada ciclo del worker.
    contrast_score: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    priority: Mapped[float] = mapped_column(Float, default=0.0, server_default="0")
    contrast: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    relaunched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    articles: Mapped[list[Article]] = relationship(back_populates="story")
    topic: Mapped[Topic | None] = relationship(back_populates="stories")


CLAIM_EXTRACTORS = ("reglas", "ia")


class Claim(Base):
    """Afirmacion comprobable extraida de un articulo."""

    __tablename__ = "claim"
    __table_args__ = (
        UniqueConstraint("article_id", "indicator", "value", name="uq_claim_article_indicator"),
        CheckConstraint(f"extractor IN {CLAIM_EXTRACTORS!r}", name="ck_claim_extractor"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    article_id: Mapped[int] = mapped_column(ForeignKey("article.id", ondelete="CASCADE"), index=True)
    story_id: Mapped[int | None] = mapped_column(
        ForeignKey("story.id", ondelete="SET NULL"), nullable=True, index=True
    )
    outlet_id: Mapped[int] = mapped_column(ForeignKey("outlet.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    indicator: Mapped[str] = mapped_column(String(60))
    geo: Mapped[str] = mapped_column(String(8))
    value: Mapped[float] = mapped_column(Float)
    unit: Mapped[str] = mapped_column(String(16))
    direction: Mapped[str | None] = mapped_column(String(8), nullable=True)  # sube | baja
    # Quien la propuso (ADR 0019): las reglas o la IA (validada por el codigo); el veredicto es del codigo.
    extractor: Mapped[str] = mapped_column(String(8), default="reglas", server_default="reglas")
    period: Mapped[str | None] = mapped_column(String(20), nullable=True)  # periodo citado en la frase
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    article: Mapped[Article] = relationship()
    outlet: Mapped[Outlet] = relationship()
    verification: Mapped[Verification | None] = relationship(back_populates="claim", uselist=False)


class Verification(Base):
    __tablename__ = "verification"
    __table_args__ = (CheckConstraint(f"verdict IN {VERDICTS!r}", name="ck_verification_verdict"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    claim_id: Mapped[int] = mapped_column(ForeignKey("claim.id", ondelete="CASCADE"), unique=True)
    verdict: Mapped[str] = mapped_column(String(16))
    confidence: Mapped[float] = mapped_column(Float)
    explanation: Mapped[str] = mapped_column(Text)
    method: Mapped[str] = mapped_column(String(40))
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    claim: Mapped[Claim] = relationship(back_populates="verification")
    evidence: Mapped[list[Evidence]] = relationship(
        back_populates="verification", cascade="all, delete-orphan"
    )


class Evidence(Base):
    __tablename__ = "evidence"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    verification_id: Mapped[int] = mapped_column(
        ForeignKey("verification.id", ondelete="CASCADE"), index=True
    )
    source: Mapped[str] = mapped_column(String(60))
    label: Mapped[str] = mapped_column(String(300))
    url: Mapped[str] = mapped_column(String(1000))
    period: Mapped[str | None] = mapped_column(String(20), nullable=True)
    value: Mapped[float | None] = mapped_column(Float, nullable=True)
    retrieved_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    payload: Mapped[dict] = mapped_column(JSON, default=dict)

    verification: Mapped[Verification] = relationship(back_populates="evidence")


PIECE_KINDS = ("analisis", "opinion")
PIECE_STATUSES = ("publicada", "revision")


class Topic(Base):
    """Tema: historias relacionadas aunque cada una tenga un enfoque distinto (ADR 0007/0008)."""

    __tablename__ = "topic"
    __table_args__ = (Index("ix_topic_country_last_seen", "country", "last_seen"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[str] = mapped_column(String(40))
    country: Mapped[str] = mapped_column(String(2))
    first_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_seen: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    n_stories: Mapped[int] = mapped_column(Integer, default=0)
    n_outlets: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    stories: Mapped[list[Story]] = relationship(back_populates="topic")
    pieces: Mapped[list[Piece]] = relationship(back_populates="topic", cascade="all, delete-orphan")


class Piece(Base):
    """Pieza propia (analisis u opinion) redactada con IA sobre un dossier verificado."""

    __tablename__ = "piece"
    __table_args__ = (
        CheckConstraint(f"kind IN {PIECE_KINDS!r}", name="ck_piece_kind"),
        CheckConstraint(f"status IN {PIECE_STATUSES!r}", name="ck_piece_status"),
        Index("ix_piece_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    topic_id: Mapped[int] = mapped_column(ForeignKey("topic.id", ondelete="CASCADE"), index=True)
    kind: Mapped[str] = mapped_column(String(16))
    status: Mapped[str] = mapped_column(String(16))
    language: Mapped[str] = mapped_column(String(8), default="es")
    title: Mapped[str] = mapped_column(String(300))
    dek: Mapped[str] = mapped_column(Text)
    body: Mapped[list] = mapped_column(JSON, default=list)
    synthesis: Mapped[dict] = mapped_column(JSON, default=dict)
    grounding: Mapped[dict] = mapped_column(JSON, default=dict)
    model: Mapped[str] = mapped_column(String(60))
    input_hash: Mapped[str] = mapped_column(String(64))
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    topic: Mapped[Topic] = relationship(back_populates="pieces")


INVESTIGATION_STATUSES = ("pendiente", "en-curso", "publicada", "error")


class Investigation(Base):
    """Investigacion a demanda sobre una pregunta (ADR 0010)."""

    __tablename__ = "investigation"
    __table_args__ = (
        CheckConstraint(f"status IN {INVESTIGATION_STATUSES!r}", name="ck_investigation_status"),
        Index("ix_investigation_status_created", "status", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    question: Mapped[str] = mapped_column(String(500))
    status: Mapped[str] = mapped_column(String(16), default="pendiente")
    language: Mapped[str] = mapped_column(String(8), default="es")
    country: Mapped[str] = mapped_column(String(2), default="ES")
    report: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


THREAD_STATUSES = ("publicado", "revision", "error")


class Thread(Base):
    """Hilo de una historia: cronologia, quien dijo que y conexiones, todo citado (ADR 0013)."""

    __tablename__ = "thread"
    __table_args__ = (
        CheckConstraint(f"status IN {THREAD_STATUSES!r}", name="ck_thread_status"),
        Index("ix_thread_status_updated", "status", "updated_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    anchor_story_id: Mapped[int | None] = mapped_column(
        ForeignKey("story.id", ondelete="SET NULL", name="fk_thread_anchor_story_id"),
        nullable=True,
        index=True,
    )
    title: Mapped[str] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(16), default="revision")
    country: Mapped[str] = mapped_column(String(2), default="ES")
    language: Mapped[str] = mapped_column(String(8), default="es")
    plan: Mapped[dict] = mapped_column(JSON, default=dict)
    content: Mapped[dict] = mapped_column(JSON, default=dict)
    sources: Mapped[list] = mapped_column(JSON, default=list)
    grounding: Mapped[dict] = mapped_column(JSON, default=dict)
    model: Mapped[str | None] = mapped_column(String(80), nullable=True)
    usage: Mapped[dict] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    anchor: Mapped[Story | None] = relationship()


SOCIAL_NETWORKS = ("x", "bluesky", "mastodon", "telegram")
SOCIAL_KINDS = ("historia", "hilo", "verificacion")
SOCIAL_STATUSES = ("prueba", "enviado", "error")


class SocialPost(Base):
    """Una pieza para una red: lo que se publico (o se habria publicado en modo prueba) y su resultado
    (ADR 0018). `kind` + `ref_id` apuntan a `story`, `thread` o `verification` sin clave foranea: el
    registro sobrevive aunque el contenido se retire."""

    __tablename__ = "social_post"
    __table_args__ = (
        CheckConstraint(f"network IN {SOCIAL_NETWORKS!r}", name="ck_social_post_network"),
        CheckConstraint(f"kind IN {SOCIAL_KINDS!r}", name="ck_social_post_kind"),
        CheckConstraint(f"status IN {SOCIAL_STATUSES!r}", name="ck_social_post_status"),
        UniqueConstraint("network", "kind", "ref_id", name="uq_social_post_network_ref"),
        Index("ix_social_post_network_created", "network", "created_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    network: Mapped[str] = mapped_column(String(16))
    kind: Mapped[str] = mapped_column(String(16))
    ref_id: Mapped[int] = mapped_column(Integer)
    language: Mapped[str] = mapped_column(String(8), default="es")
    score: Mapped[float] = mapped_column(Float, default=0.0)
    text: Mapped[str] = mapped_column(Text)
    link: Mapped[str] = mapped_column(String(1000))
    image_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    status: Mapped[str] = mapped_column(String(16))
    external_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    external_url: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
