from __future__ import annotations

from abc import ABC, abstractmethod

from app.llm.router import LLMCallResult


class BaseLLMRouter(ABC):
    @abstractmethod
    def call(
        self,
        stage_name: str,
        system: str,
        user: str,
        *,
        max_tokens: int,
        temperature: float | None = None,
    ) -> LLMCallResult: ...

