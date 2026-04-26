from __future__ import annotations

from typing import Literal

from app.core.config import get_settings
from app.llm.anthropic_router import AnthropicRouter
from app.llm.base import BaseLLMRouter
from app.llm.openai_router import OpenAIRouter
from app.llm.router import LLMCallResult, ModelConfig

LLMProvider = Literal["anthropic", "openai"]


def make_router() -> BaseLLMRouter:
    settings = get_settings()
    provider = getattr(settings, "llm_provider", "anthropic")
    if provider == "openai":
        return OpenAIRouter()
    return AnthropicRouter()


__all__ = [
    "AnthropicRouter",
    "BaseLLMRouter",
    "LLMCallResult",
    "LLMProvider",
    "ModelConfig",
    "OpenAIRouter",
    "make_router",
]

