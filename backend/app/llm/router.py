from __future__ import annotations

import hashlib
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
    cached: bool = False


def get_prompt_hash(model: str, system: str, user: str, temperature: float, max_tokens: int) -> str:
    payload = f"{model}:{temperature}:{max_tokens}:{system}:{user}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()

