from __future__ import annotations

import logging

import openai
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
    openai.APIConnectionError,
    openai.APITimeoutError,
    openai.RateLimitError,
    openai.InternalServerError,
)


class OpenAIRouter(BaseLLMRouter):
    def __init__(self, *, overrides: dict[str, ModelConfig] | None = None) -> None:
        settings = get_settings()
        self._client = openai.OpenAI(
            api_key=settings.openai_api_key,
            timeout=30.0,
        )

        def _normalize_openai_model(name: str, *, fallback: str) -> str:
            # AutoResearch historically used Claude for proposer; when the selected provider
            # is OpenAI we must ensure the model name is an OpenAI model.
            lowered = (name or "").lower()
            if lowered.startswith("claude"):
                logger.warning(
                    "Model %r is a Claude model but provider=openai; falling back to %r",
                    name,
                    fallback,
                )
                return fallback
            return name

        proposer_model = _normalize_openai_model(
            settings.proposer_model, fallback=_normalize_openai_model(settings.judge_model, fallback="gpt-4o-mini")
        )
        judge_model = _normalize_openai_model(settings.judge_model, fallback="gpt-4o-mini")

        self._routing_table: dict[str, ModelConfig] = {
            "autoresearch_proposer": ModelConfig(model=proposer_model, temperature=0.3),
            "autoresearch_judge": ModelConfig(model=judge_model, temperature=0.0),
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
        def _call() -> openai.types.chat.ChatCompletion:
            return self._client.chat.completions.create(
                model=cfg.model,
                temperature=effective_temperature,
                max_tokens=max_tokens,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
            )

        resp = _call()
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        return LLMCallResult(
            content=text,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=cfg.model,
        )

