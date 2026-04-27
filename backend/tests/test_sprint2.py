"""Sprint 2 regression tests.

Covers:
  S2-2  temperature is forwarded to the router (not silently dropped)
  S2-3  LLMJudgeEvaluator truncates oversized target files
  S2-4  _build_diff_view handles multi-hunk and multi-file diffs correctly
  S2-5  _read_target prefers session worktree over folder_path
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


# ---------------------------------------------------------------------------
# S2-2 — temperature threading
# ---------------------------------------------------------------------------

class TestTemperatureThreading:
    def test_proposer_passes_temperature_to_router(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.agent import llm as agent_llm

        calls: list[dict] = []

        class _DummyRouter:
            def call(self, stage_name, system, user, *, max_tokens, temperature=None):
                calls.append({"stage": stage_name, "temperature": temperature})
                from app.llm.router import LLMCallResult
                return LLMCallResult(
                    content="ok", input_tokens=5, output_tokens=5, model="dummy"
                )

        monkeypatch.setattr(agent_llm, "make_router", lambda: _DummyRouter())
        agent_llm._router.cache_clear()

        p = agent_llm.ProposerClient()
        p.complete("sys", "user", max_output_tokens=100, temperature=0.7)

        assert calls[0]["temperature"] == 0.7

    def test_judge_passes_temperature_to_router(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.agent import llm as agent_llm

        calls: list[dict] = []

        class _DummyRouter:
            def call(self, stage_name, system, user, *, max_tokens, temperature=None):
                calls.append({"stage": stage_name, "temperature": temperature})
                from app.llm.router import LLMCallResult
                return LLMCallResult(
                    content="ok", input_tokens=5, output_tokens=5, model="dummy"
                )

        monkeypatch.setattr(agent_llm, "make_router", lambda: _DummyRouter())
        agent_llm._router.cache_clear()

        j = agent_llm.JudgeClient()
        j.complete("sys", "user", max_output_tokens=100, temperature=0.0)

        assert calls[0]["temperature"] == 0.0

    def test_anthropic_router_uses_override_temperature(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import app.llm.anthropic_router as ant_mod
        from app.llm.router import ModelConfig

        recorded: list[float] = []

        class _FakeMsg:
            content = [MagicMock(type="text", text="hello")]
            usage = MagicMock(input_tokens=1, output_tokens=1)

        class _FakeMsgs:
            @staticmethod
            def create(*, model, system, max_tokens, temperature, messages):
                recorded.append(temperature)
                return _FakeMsg()

        class _FakeClient:
            messages = _FakeMsgs()

        class _FakeSettings:
            anthropic_api_key = "test"
            proposer_model = "claude-test"
            judge_model = "claude-judge"

        monkeypatch.setattr(ant_mod, "get_settings", lambda: _FakeSettings())
        monkeypatch.setattr(ant_mod.anthropic, "Anthropic", lambda **kw: _FakeClient())

        router = ant_mod.AnthropicRouter()
        # Default from routing table for proposer is 0.3; override to 0.9.
        router.call("autoresearch_proposer", "sys", "user", max_tokens=10, temperature=0.9)
        assert recorded == [0.9]

    def test_anthropic_router_falls_back_to_routing_table_temperature(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import app.llm.anthropic_router as ant_mod

        recorded: list[float] = []

        class _FakeMsg:
            content = [MagicMock(type="text", text="hello")]
            usage = MagicMock(input_tokens=1, output_tokens=1)

        class _FakeMsgs:
            @staticmethod
            def create(*, model, system, max_tokens, temperature, messages):
                recorded.append(temperature)
                return _FakeMsg()

        class _FakeClient:
            messages = _FakeMsgs()

        class _FakeSettings:
            anthropic_api_key = "test"
            proposer_model = "claude-test"
            judge_model = "claude-judge"

        monkeypatch.setattr(ant_mod, "get_settings", lambda: _FakeSettings())
        monkeypatch.setattr(ant_mod.anthropic, "Anthropic", lambda **kw: _FakeClient())

        router = ant_mod.AnthropicRouter()
        # No temperature arg → should use routing table default (0.3 for proposer).
        router.call("autoresearch_proposer", "sys", "user", max_tokens=10)
        assert recorded == [0.3]


# ---------------------------------------------------------------------------
# S2-3 — LLMJudgeEvaluator context window guard
# ---------------------------------------------------------------------------

class TestLLMJudgeContextGuard:
    def _make_evaluator(self):
        from app.evaluators.llm_judge import LLMJudgeEvaluator
        from unittest.mock import MagicMock
        row = MagicMock()
        row.config = {
            "target_file": "target.md",
            "rubric_path": "rubric.md",
            "score_range": [0, 100],
            "max_output_tokens": 200,
        }
        return LLMJudgeEvaluator(row=row, secrets={})

    def test_small_file_passes_untruncated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        ev = self._make_evaluator()
        (tmp_path / "target.md").write_text("Short content.\n")
        (tmp_path / "rubric.md").write_text("Score quality.\n")

        captured_user: list[str] = []

        class _FakeClient:
            def complete(self, system, user, max_output_tokens, temperature=0.0):
                captured_user.append(user)
                from app.agent.llm import LLMResult
                return LLMResult(
                    text='{"score": 75, "rationale": "good"}',
                    input_tokens=10,
                    output_tokens=10,
                    model="gpt-4o-mini",
                )

        monkeypatch.setattr(
            "app.evaluators.llm_judge.JudgeClient", lambda **kw: _FakeClient()
        )

        result = ev.evaluate(tmp_path)
        assert result.score == 75
        assert "[TRUNCATED" not in captured_user[0]

    def test_oversized_file_is_truncated(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from app.evaluators import llm_judge as judge_mod

        ev = self._make_evaluator()
        # Write a file that will exceed the budget when estimated.
        big_content = "word " * 200_000  # ~200k tokens estimated
        (tmp_path / "target.md").write_text(big_content)
        (tmp_path / "rubric.md").write_text("Score quality.\n")

        # Patch estimate_tokens to give predictable results.
        def _fake_estimate(text: str, model: str = "gpt-4o-mini") -> int:
            # Rubric+system = small; target = huge.
            if "word " in text:
                return 200_000
            return 500

        monkeypatch.setattr(judge_mod, "estimate_tokens", _fake_estimate)

        captured_user: list[str] = []

        class _FakeClient:
            def complete(self, system, user, max_output_tokens, temperature=0.0):
                captured_user.append(user)
                from app.agent.llm import LLMResult
                return LLMResult(
                    text='{"score": 50, "rationale": "truncated"}',
                    input_tokens=10,
                    output_tokens=10,
                    model="gpt-4o-mini",
                )

        monkeypatch.setattr(judge_mod, "JudgeClient", lambda **kw: _FakeClient())

        result = ev.evaluate(tmp_path)
        assert result.score == 50
        assert "[TRUNCATED" in captured_user[0]


# ---------------------------------------------------------------------------
# S2-4 — _build_diff_view multi-hunk and multi-file
# ---------------------------------------------------------------------------

class TestBuildDiffView:
    @staticmethod
    def _call(diff_text):
        from app.api.routes.experiments import _build_diff_view
        return _build_diff_view(diff_text)

    def test_returns_none_for_empty(self) -> None:
        assert self._call(None) is None
        assert self._call("") is None

    def test_single_hunk(self) -> None:
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,3 @@\n"
            " context\n"
            "-old\n"
            "+new\n"
        )
        view = self._call(diff)
        assert view is not None
        assert view.file_path == "foo.py"
        assert "old" in view.old_text
        assert "new" in view.new_text
        assert "context" in view.old_text and "context" in view.new_text

    def test_multi_hunk_same_file(self) -> None:
        diff = (
            "diff --git a/foo.py b/foo.py\n"
            "--- a/foo.py\n"
            "+++ b/foo.py\n"
            "@@ -1,3 +1,3 @@\n"
            " ctx1\n"
            "-old1\n"
            "+new1\n"
            "@@ -10,3 +10,3 @@\n"
            " ctx2\n"
            "-old2\n"
            "+new2\n"
        )
        view = self._call(diff)
        assert view is not None
        assert view.file_path == "foo.py"
        # Both hunks should appear
        assert "old1" in view.old_text
        assert "old2" in view.old_text
        assert "new1" in view.new_text
        assert "new2" in view.new_text

    def test_multi_file_only_renders_first(self) -> None:
        diff = (
            "diff --git a/file1.py b/file1.py\n"
            "--- a/file1.py\n"
            "+++ b/file1.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old1\n"
            "+new1\n"
            "diff --git a/file2.py b/file2.py\n"
            "--- a/file2.py\n"
            "+++ b/file2.py\n"
            "@@ -1,1 +1,1 @@\n"
            "-old2\n"
            "+new2\n"
        )
        view = self._call(diff)
        assert view is not None
        assert view.file_path == "file1.py"
        assert "old1" in view.old_text
        assert "new1" in view.new_text
        # Second file must not bleed through
        assert "old2" not in view.old_text
        assert "new2" not in view.new_text


# ---------------------------------------------------------------------------
# S2-5 — _read_target prefers session worktree
# ---------------------------------------------------------------------------

class TestReadTargetWorktree:
    def test_reads_from_worktree_when_present(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.agent import context as ctx_mod

        # Create mock worktree at tmp_path/worktrees/session-abc123
        worktree_root = tmp_path / "worktrees"
        session_worktree = worktree_root / "session-abc123"
        session_worktree.mkdir(parents=True)
        (session_worktree / "target.md").write_text("worktree version\n")

        # Also create a file in the repo root (folder_path).
        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "target.md").write_text("repo root version\n")

        # Patch settings to point worktree_root at our tmp location.
        fake_settings = MagicMock()
        fake_settings.worktree_root = worktree_root
        monkeypatch.setattr(ctx_mod, "get_settings", lambda: fake_settings)

        result = ctx_mod._read_target(str(repo_root), "target.md", session_id="abc123")
        assert result == "worktree version\n"

    def test_falls_back_to_folder_path_when_worktree_missing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.agent import context as ctx_mod

        worktree_root = tmp_path / "worktrees"
        worktree_root.mkdir()
        # Do NOT create the session worktree.

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "target.md").write_text("repo root version\n")

        fake_settings = MagicMock()
        fake_settings.worktree_root = worktree_root
        monkeypatch.setattr(ctx_mod, "get_settings", lambda: fake_settings)

        result = ctx_mod._read_target(str(repo_root), "target.md", session_id="missing-session")
        assert result == "repo root version\n"

    def test_falls_back_when_no_session_id(self, tmp_path: Path) -> None:
        from app.agent import context as ctx_mod

        repo_root = tmp_path / "repo"
        repo_root.mkdir()
        (repo_root / "target.md").write_text("repo root only\n")

        result = ctx_mod._read_target(str(repo_root), "target.md", session_id=None)
        assert result == "repo root only\n"
