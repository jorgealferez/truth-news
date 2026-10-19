"""Coste de la IA: lo que cuesta cada llamada, por ciclo y por dia, con tope diario (ADR 0054)."""

from __future__ import annotations

import threading
from collections import Counter

# USD por millon de tokens: (entrada, salida, lectura de cache, escritura de cache de 5 min). Precios de la
# API de Anthropic a 2026-10-06. El pensamiento se factura como salida y ya viene en output_tokens.
PRICES: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-5-5": (4.0, 20.0, 0.20, 5.0),
    "claude-opus-5": (5.0, 25.0, 0.50, 6.25),
    "claude-opus-4-8": (5.0, 25.0, 0.50, 6.25),
    "claude-sonnet-5-5": (2.0, 10.0, 0.20, 2.5),
    "claude-haiku-5-5": (0.10, 0.50, 0.01, 0.125),
}
# Un modelo que no esta en la tabla (p. ej. el de respaldo ante un rechazo) se cuenta al precio mas alto de
# los de arriba: el tope diario nunca se queda corto por un precio que falta.
UNKNOWN = max(PRICES.values())
USAGE_KEYS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


class BudgetExceeded(RuntimeError):
    """El gasto de hoy ya llego al tope diario: no se hace la llamada."""


def call_cost(model: str, usage: dict) -> float:
    # El nombre mas largo primero: "claude-opus-5-5" no debe caer en el precio de "claude-opus-5".
    by_length = sorted(PRICES.items(), key=lambda kv: -len(kv[0]))
    price = next((p for name, p in by_length if model.startswith(name)), UNKNOWN)
    tokens = [usage.get(k) or 0 for k in USAGE_KEYS]
    return sum(t * p for t, p in zip(tokens, price, strict=True)) / 1_000_000


class Meter:
    """Contador del ciclo. Las piezas se piden en paralelo, asi que suma con candado."""

    def __init__(self, spent_before: float = 0.0, daily_budget: float = 0.0):
        self.spent_before = spent_before  # lo gastado hoy en ciclos anteriores
        self.daily_budget = daily_budget  # 0 = sin tope
        self.spent = 0.0
        self.calls = 0
        self.by_model: Counter = Counter()
        self._lock = threading.Lock()

    def check(self) -> None:
        if self.daily_budget > 0 and self.spent_before + self.spent >= self.daily_budget:
            total = self.spent_before + self.spent
            raise BudgetExceeded(
                f"presupuesto diario de IA agotado ({total:.2f} de {self.daily_budget:.2f} USD)"
            )

    def charge(self, model: str, usage: dict) -> float:
        cost = call_cost(model, usage)
        with self._lock:
            self.spent += cost
            self.calls += 1
            self.by_model[model] += cost
        return cost

    def summary(self) -> dict:
        return {
            "usd": round(self.spent, 4),
            "llamadas": self.calls,
            "por_modelo": {m: round(v, 4) for m, v in self.by_model.items()},
            "hoy_usd": round(self.spent_before + self.spent, 4),
            "tope_diario_usd": self.daily_budget,
        }


# El contador del ciclo en curso. El worker lo cambia al empezar cada ciclo; fuera del worker (tests, CLI)
# cuenta sin tope.
METER = Meter()


def start_cycle(spent_before: float, daily_budget: float) -> Meter:
    global METER
    METER = Meter(spent_before, daily_budget)
    return METER
