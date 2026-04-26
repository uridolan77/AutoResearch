from __future__ import annotations

import anthropic

from app.core.config import get_settings
from app.llm.base import BaseLLMRouter
from app.llm.router import LLMCallResult, ModelConfig


class AnthropicRouter(BaseLLMRouter):
    def __init__(self, *, overrides: dict[str, ModelConfig] | None = None) -> None:
        settings = get_settings()
        self._client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._routing_table: dict[str, ModelConfig] = {
            "autoresearch_proposer": ModelConfig(model=settings.proposer_model, temperature=0.3),
            "autoresearch_judge": ModelConfig(model=settings.judge_model, temperature=0.0),
        }
        if overrides:
            self._routing_table.update(overrides)

    def call(
        self,
        stage_name: str,
        system: str,
        user: str,
        *,
        max_tokens: int,
    ) -> LLMCallResult:
        cfg = self._routing_table.get(stage_name)
        if cfg is None:
            raise ValueError(f"Unknown LLM stage: {stage_name}")

        resp = self._client.messages.create(
            model=cfg.model,
            system=system,
            max_tokens=max_tokens,
            temperature=cfg.temperature,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        return LLMCallResult(
            content=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            model=cfg.model,
            cached=False,
        )

