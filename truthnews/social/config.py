"""Configuracion de redes por variables de entorno. Las credenciales solo viven en Railway."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_QUOTA = {"x": 4, "bluesky": 6, "mastodon": 6, "telegram": 8}

# Variables que necesita cada red para enviar de verdad; sin ellas, modo prueba.
CREDENTIALS = {
    "bluesky": ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"),
    "mastodon": ("MASTODON_URL", "MASTODON_TOKEN"),
    "telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
    "x": ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"),
}


def _quota() -> dict[str, int]:
    """`SOCIAL_DAILY_QUOTA=x:4,bluesky:6`: lo que no se nombra conserva el valor por defecto."""
    quota = dict(DEFAULT_QUOTA)
    for part in os.environ.get("SOCIAL_DAILY_QUOTA", "").split(","):
        name, _, value = part.partition(":")
        if name.strip() in quota and value.strip().isdigit():
            quota[name.strip()] = int(value)
    return quota


def _flag(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    return default if raw is None else raw.strip().lower() in {"1", "true", "yes", "si", "on"}


@dataclass(frozen=True)
class SocialSettings:
    enabled: bool = field(default_factory=lambda: _flag("SOCIAL_ENABLED", True))
    dry_run: bool = field(default_factory=lambda: _flag("SOCIAL_DRY_RUN", False))
    quota: dict[str, int] = field(default_factory=_quota)
    min_score: float = field(default_factory=lambda: float(os.environ.get("SOCIAL_MIN_SCORE", "2")))
    window_hours: int = field(default_factory=lambda: int(os.environ.get("SOCIAL_WINDOW_HOURS", "72")))
    per_cycle: int = field(default_factory=lambda: int(os.environ.get("SOCIAL_PER_CYCLE", "2")))
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))

    def credentials(self, network: str) -> dict[str, str] | None:
        """Las credenciales de la red, o None si falta alguna (o si se fuerza el modo prueba)."""
        names = CREDENTIALS[network]
        values = {n: self.env.get(n, "").strip() for n in names}
        if self.dry_run or not all(values.values()):
            return None
        return values
