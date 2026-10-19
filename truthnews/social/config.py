"""Configuracion de redes por variables de entorno. Las credenciales solo viven en Railway."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

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


def _hours(raw: str) -> tuple[int, int]:
    """'8-23' -> (8, 23). Un valor mal escrito deja el de por defecto."""
    start, _, end = raw.partition("-")
    if start.strip().isdigit() and end.strip().isdigit() and 0 <= int(start) < int(end) <= 24:
        return int(start), int(end)
    return 8, 23


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
    # Horas activas en hora de Madrid, [inicio, fin): fuera de ellas no se publica nada nuevo; dentro, cada
    # red espera (horas activas / cupo) entre piezas para repartirlas en el dia en vez de llenar el cupo de
    # madrugada (medido 2026-10-19: cupos llenos antes de las 07:35 UTC).
    spread: bool = field(default_factory=lambda: _flag("SOCIAL_SPREAD", True))
    active_hours: tuple[int, int] = field(
        default_factory=lambda: _hours(os.environ.get("SOCIAL_ACTIVE_HOURS", "8-23"))
    )
    env: dict[str, str] = field(default_factory=lambda: dict(os.environ))

    def gap_minutes(self, network: str) -> float:
        """Separacion minima entre dos piezas de la misma red para repartir el cupo en las horas activas."""
        quota = self.quota.get(network, 0)
        start, end = self.active_hours
        return (end - start) * 60 / quota if quota else float("inf")

    def credentials(self, network: str) -> dict[str, str] | None:
        """Las credenciales de la cuenta, o None si falta alguna (o si se fuerza el modo prueba)."""
        base = CREDENTIALS[base_network(network)]
        values = {b: self.env.get(n, "").strip() for b, n in zip(base, env_names(network), strict=True)}
        if self.dry_run or not all(values.values()):
            return None
        return values  # con los nombres de la red base, que son los que leen los adaptadores


def _last_sunday(year: int, month: int) -> datetime:
    day = (
        datetime(year, month + 1, 1, tzinfo=UTC) - timedelta(days=1)
        if month < 12
        else datetime(year, 12, 31, tzinfo=UTC)
    )
    return day - timedelta(days=(day.weekday() + 1) % 7)


def madrid_hour(now: datetime) -> int:
    """Hora local de Madrid sin depender de tzdata (la imagen slim no la trae): UTC+1, y UTC+2 en horario
    de verano de la UE (desde el ultimo domingo de marzo hasta el ultimo de octubre, a la 01:00 UTC)."""
    now = now if now.tzinfo else now.replace(tzinfo=UTC)
    summer_start = _last_sunday(now.year, 3).replace(hour=1)
    summer_end = _last_sunday(now.year, 10).replace(hour=1)
    offset = 2 if summer_start <= now < summer_end else 1
    return (now.astimezone(UTC) + timedelta(hours=offset)).hour
