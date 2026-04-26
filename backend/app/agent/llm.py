"""LLM adapter for proposer (Claude Sonnet 4.5) and judge (GPT-4o-mini).

Different providers by design — decorrelates judge bias from proposer style.
Per-call token usage is returned alongside the text so callers can enforce
session and per-iteration token caps before re-entry.
"""
from __future__ import annotations

from dataclasses import dataclass

import anthropic
import openai
try:
    import tiktoken  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    tiktoken = None  # type: ignore

from app.core.config import get_settings


@dataclass
class LLMResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens


def estimate_tokens(text: str, model: str = "gpt-4o-mini") -> int:
    """Cheap pre-call token estimate. tiktoken cl100k_base is close enough
    for both Claude and GPT for budget gating purposes."""
    if tiktoken is None:
        # Fallback heuristic (~4 chars/token for English-ish text). This is only
        # used when tiktoken isn't installed in the runtime.
        return max(1, len(text) // 4)
    try:
        enc = tiktoken.encoding_for_model(model)
    except KeyError:
        enc = tiktoken.get_encoding("cl100k_base")
    return len(enc.encode(text))


class ProposerClient:
    """Claude Sonnet 4.5 — strongest code + prose editor at tolerable cost."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.proposer_model
        self.client = anthropic.Anthropic(api_key=api_key or settings.anthropic_api_key)

    def complete(
        self,
        system: str,
        user: str,
        max_output_tokens: int,
        temperature: float = 0.3,
    ) -> LLMResult:
        resp = self.client.messages.create(
            model=self.model,
            system=system,
            max_tokens=max_output_tokens,
            temperature=temperature,
            messages=[{"role": "user", "content": user}],
        )
        text = "".join(
            block.text for block in resp.content if getattr(block, "type", None) == "text"
        )
        return LLMResult(
            text=text,
            input_tokens=resp.usage.input_tokens,
            output_tokens=resp.usage.output_tokens,
            model=self.model,
        )


class JudgeClient:
    """GPT-4o-mini — different provider for evaluator decorrelation."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.judge_model
        self.client = openai.OpenAI(api_key=api_key or settings.openai_api_key)

    def complete(
        self,
        system: str,
        user: str,
        max_output_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResult:
        resp = self.client.chat.completions.create(
            model=self.model,
            temperature=temperature,
            max_tokens=max_output_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        text = resp.choices[0].message.content or ""
        usage = resp.usage
        return LLMResult(
            text=text,
            input_tokens=usage.prompt_tokens if usage else estimate_tokens(system + user),
            output_tokens=usage.completion_tokens if usage else estimate_tokens(text),
            model=self.model,
        )
