from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.core.config import get_settings
from app.llm import make_router
from app.llm.anthropic_router import AnthropicRouter
from app.llm.openai_router import OpenAIRouter
from app.llm.router import LLMCallResult


def _clear_settings_cache() -> None:
    get_settings.cache_clear()  # type: ignore[attr-defined]


def test_make_router_selects_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AR_LLM_PROVIDER", "openai")
    _clear_settings_cache()
    router = make_router()
    assert isinstance(router, OpenAIRouter)


def test_make_router_selects_anthropic(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AR_LLM_PROVIDER", "anthropic")
    _clear_settings_cache()
    router = make_router()
    assert isinstance(router, AnthropicRouter)


@dataclass
class _DummyRouter:
    calls: list[str]

    def call(self, stage_name: str, system: str, user: str, *, max_tokens: int) -> LLMCallResult:
        self.calls.append(stage_name)
        return LLMCallResult(
            content=f"{stage_name}:{max_tokens}",
            input_tokens=11,
            output_tokens=22,
            model="dummy-model",
            cached=False,
        )


def test_agent_clients_use_router_stages(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.agent import llm as agent_llm

    dummy = _DummyRouter(calls=[])

    monkeypatch.setattr(agent_llm, "make_router", lambda: dummy)
    agent_llm._router.cache_clear()  # type: ignore[attr-defined]

    p = agent_llm.ProposerClient()
    pres = p.complete("sys", "user", max_output_tokens=123)
    assert pres.text.startswith("autoresearch_proposer:")
    assert pres.input_tokens == 11
    assert pres.output_tokens == 22

    j = agent_llm.JudgeClient()
    jres = j.complete("sys", "user", max_output_tokens=456)
    assert jres.text.startswith("autoresearch_judge:")
    assert jres.input_tokens == 11
    assert jres.output_tokens == 22

    assert dummy.calls == ["autoresearch_proposer", "autoresearch_judge"]

