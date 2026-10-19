"""Configuracion de redes por variables de entorno. Las credenciales solo viven en Railway."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

DEFAULT_QUOTA = {
    "x": 4,
    "bluesky": 6,
    "mastodon": 6,
    "telegram": 8,
    "x_en": 2,
    "bluesky_en": 3,
    "mastodon_en": 3,
    "telegram_en": 4,
}

# Variables que necesita cada red para enviar de verdad; sin ellas, modo prueba.
CREDENTIALS = {
    "bluesky": ("BLUESKY_HANDLE", "BLUESKY_APP_PASSWORD"),
    "mastodon": ("MASTODON_URL", "MASTODON_TOKEN"),
    "telegram": ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"),
    "x": ("X_API_KEY", "X_API_SECRET", "X_ACCESS_TOKEN", "X_ACCESS_SECRET"),
}


def base_network(network: str) -> str:
    """'x_en' -> 'x': la cuenta en ingles usa el mismo adaptador y los mismos limites."""
    return network.removesuffix("_en")


def env_names(network: str) -> tuple[str, ...]:
    """Variables de la cuenta: las de la red base y, para `*_en`, con prefijo propio (`X_EN_API_KEY`)."""
    names = CREDENTIALS[base_network(network)]
    if network.endswith("_en"):
        prefix = base_network(network).upper()
        return tuple(n.replace(prefix + "_", prefix + "_EN_", 1) for n in names)
    return names


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
        """Las credenciales de la cuenta, o None si falta alguna (o si se fuerza el modo prueba)."""
        base = CREDENTIALS[base_network(network)]
        values = {b: self.env.get(n, "").strip() for b, n in zip(base, env_names(network), strict=True)}
        if self.dry_run or not all(values.values()):
            return None
        return values  # con los nombres de la red base, que son los que leen los adaptadores
