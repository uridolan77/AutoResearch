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


def test_openai_router_normalizes_claude_models(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.llm import openai_router as oai_mod

    class _S:
        openai_api_key = "test"
        proposer_model = "claude-sonnet-4-5"
        judge_model = "gpt-4o-mini"

    monkeypatch.setattr(oai_mod, "get_settings", lambda: _S())

    class _FakeChat:
        class completions:
            @staticmethod
            def create(*, model: str, **kwargs):
                class _U:
                    prompt_tokens = 1
                    completion_tokens = 1

                class _M:
                    content = "ok"

                class _C:
                    message = _M()

                class _R:
                    choices = [_C()]
                    usage = _U()

                # Assert we never send Claude model IDs to OpenAI.
                assert not model.lower().startswith("claude")
                return _R()

    class _FakeClient:
        chat = _FakeChat()

    monkeypatch.setattr(oai_mod.openai, "OpenAI", lambda api_key: _FakeClient())

    r = oai_mod.OpenAIRouter()
    out = r.call("autoresearch_proposer", "s", "u", max_tokens=10)
    assert out.model == "gpt-4o-mini"
    assert out.content == "ok"


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

