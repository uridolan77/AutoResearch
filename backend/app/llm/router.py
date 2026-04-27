from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    model: str
    temperature: float = 0.2


@dataclass(frozen=True)
class LLMCallResult:
    content: str
    input_tokens: int
    output_tokens: int
    model: str

