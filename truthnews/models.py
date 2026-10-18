"""Modelo de datos (ADR 0002). Cada cambio de este fichero lleva su ADR `Tipo: datos`."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text
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

    outlet: Mapped[Outlet] = relationship()


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
