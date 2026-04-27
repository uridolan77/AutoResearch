from __future__ import annotations

import logging

import anthropic
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import get_settings
from app.llm.base import BaseLLMRouter
from app.llm.router import LLMCallResult, ModelConfig

logger = logging.getLogger(__name__)

_RETRYABLE = (
    anthropic.APIConnectionError,
    anthropic.APITimeoutError,
    anthropic.RateLimitError,
    anthropic.InternalServerError,
)


class AnthropicRouter(BaseLLMRouter):
    def __init__(self, *, overrides: dict[str, ModelConfig] | None = None) -> None:
        settings = get_settings()
        self._client = anthropic.Anthropic(
            api_key=settings.anthropic_api_key,
            timeout=30.0,
        )
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
        temperature: float | None = None,
    ) -> LLMCallResult:
        cfg = self._routing_table.get(stage_name)
        if cfg is None:
            raise ValueError(f"Unknown LLM stage: {stage_name}")

        effective_temperature = temperature if temperature is not None else cfg.temperature

        @retry(
            retry=retry_if_exception_type(_RETRYABLE),
            wait=wait_exponential(multiplier=1, min=2, max=60),
            stop=stop_after_attempt(3),
            reraise=True,
        )
        def _call() -> anthropic.types.Message:
            return self._client.messages.create(
                model=cfg.model,
                system=system,
                max_tokens=max_tokens,
                temperature=effective_temperature,
                messages=[{"role": "user", "content": user}],
            )

        resp = _call()
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        return LLMCallResult(
            content=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            model=cfg.model,
        )

