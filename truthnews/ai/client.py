"""Cliente de la API de Anthropic con salida estructurada (ADR 0007)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

FALLBACK_BETA = "server-side-fallback-2026-07-01"


class AIError(RuntimeError):
    """La respuesta no se puede usar (rechazo, truncada o sin JSON valido): no se publica nada."""


@dataclass
class AIResult:
    data: dict
    model: str
    usage: dict = field(default_factory=dict)


class AIClient:
    def __init__(
        self,
        model: str = "claude-opus-5-5",
        effort: str = "high",
        client: Any = None,
        max_tokens: int = 64000,
    ):
        if client is None:  # pragma: no cover - requiere ANTHROPIC_API_KEY
            import anthropic

            client = anthropic.Anthropic()
        self._client = client
        self.model = model
        self.effort = effort
        self.max_tokens = max_tokens

    def structured(self, system: str, user: str, schema: dict) -> AIResult:
        """Una llamada con salida JSON validada por esquema. El prompt de sistema es estable y se cachea."""
        with self._client.beta.messages.stream(
            model=self.model,
            max_tokens=self.max_tokens,
            system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": user}],
            thinking={"type": "adaptive"},
            output_config={"effort": self.effort, "format": {"type": "json_schema", "schema": schema}},
            betas=[FALLBACK_BETA],
            fallbacks="default",
        ) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason == "refusal":
            raise AIError(f"rechazo del modelo ({getattr(msg.stop_details, 'category', None)})")
        if msg.stop_reason == "max_tokens":
            raise AIError("respuesta truncada por max_tokens")
        text = next((b.text for b in msg.content if b.type == "text"), None)
        if not text:
            raise AIError("respuesta sin texto")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise AIError(f"JSON invalido: {exc}") from exc
        u = msg.usage
        usage = {
            k: getattr(u, k, None)
            for k in (
                "input_tokens",
                "output_tokens",
                "cache_read_input_tokens",
                "cache_creation_input_tokens",
            )
        }
        return AIResult(data=data, model=getattr(msg, "model", self.model), usage=usage)
