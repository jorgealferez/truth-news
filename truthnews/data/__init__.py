"""Conectores a fuentes de datos oficiales y abiertas. Todos devuelven `Observation` trazables."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime

import httpx

# Identificacion honesta del proyecto. El WAF del INE rechaza agentes que contienen "Bot" (medido: 403).
USER_AGENT = "truth-news-datos/0.1 (+https://github.com/jorgealferez/truth-news)"
STALE_AFTER_DAYS = 400


@dataclass
class Observation:
    source: str
    label: str
    url: str
    period: str
    value: float
    retrieved_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    previous: Observation | None = None
    extra: dict = field(default_factory=dict)

    def period_end(self) -> date:
        """Ultimo dia aproximado del periodo ('2026-08', '2026-Q2', '2025')."""
        p = self.period
        if "-Q" in p:
            year, q = p.split("-Q")
            return date(int(year), int(q) * 3, 28)
        if len(p) == 7:
            return date(int(p[:4]), int(p[5:7]), 28)
        return date(int(p[:4]), 12, 31)

    def is_stale(self, today: date | None = None) -> bool:
        today = today or datetime.now(UTC).date()
        return (today - self.period_end()).days > STALE_AFTER_DAYS


def client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True, transport=transport
    )
