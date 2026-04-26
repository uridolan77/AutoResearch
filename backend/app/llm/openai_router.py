from __future__ import annotations

import openai

from app.core.config import get_settings
from app.llm.base import BaseLLMRouter
from app.llm.router import LLMCallResult, ModelConfig


class OpenAIRouter(BaseLLMRouter):
    def __init__(self, *, overrides: dict[str, ModelConfig] | None = None) -> None:
        settings = get_settings()
        self._client = openai.OpenAI(api_key=settings.openai_api_key)
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

        resp = self._client.chat.completions.create(
            model=cfg.model,
            temperature=cfg.temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        return LLMCallResult(
            content=text,
            input_tokens=usage.prompt_tokens if usage else 0,
            output_tokens=usage.completion_tokens if usage else 0,
            model=cfg.model,
            cached=False,
        )

