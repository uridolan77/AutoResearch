"""LLM adapter for proposer (Claude Sonnet 4.5) and judge (GPT-4o-mini).

Different providers by design — decorrelates judge bias from proposer style.
Per-call token usage is returned alongside the text so callers can enforce
session and per-iteration token caps before re-entry.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

try:
    import tiktoken  # type: ignore
except ModuleNotFoundError:  # pragma: no cover
    tiktoken = None  # type: ignore

from app.core.config import get_settings
from app.llm import make_router


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


@lru_cache
def _router():
    return make_router()


def _clear_router_cache() -> None:  # used by tests to reset between test cases
    _router.cache_clear()
    from app.core.config import get_settings
    get_settings.cache_clear()


class ProposerClient:
    """Claude Sonnet 4.5 — strongest code + prose editor at tolerable cost."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.proposer_model
        self._api_key = api_key

    def complete(
        self,
        system: str,
        user: str,
        max_output_tokens: int,
        temperature: float = 0.3,
    ) -> LLMResult:
        result = _router().call(
            "autoresearch_proposer",
            system,
            user,
            max_tokens=max_output_tokens,
            temperature=temperature,
        )
        return LLMResult(
            text=result.content,
            input_tokens=result.input_tokens or estimate_tokens(system + user, model=result.model),
            output_tokens=result.output_tokens or estimate_tokens(result.content, model=result.model),
            model=result.model,
        )


class JudgeClient:
    """GPT-4o-mini — different provider for evaluator decorrelation."""

    def __init__(self, api_key: str | None = None, model: str | None = None) -> None:
        settings = get_settings()
        self.model = model or settings.judge_model
        self._api_key = api_key

    def complete(
        self,
        system: str,
        user: str,
        max_output_tokens: int,
        temperature: float = 0.0,
    ) -> LLMResult:
        result = _router().call(
            "autoresearch_judge",
            system,
            user,
            max_tokens=max_output_tokens,
            temperature=temperature,
        )
        return LLMResult(
            text=result.content,
            input_tokens=result.input_tokens or estimate_tokens(system + user, model=result.model),
            output_tokens=result.output_tokens or estimate_tokens(result.content, model=result.model),
            model=result.model,
        )
