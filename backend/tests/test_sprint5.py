"""Sprint 5/6 tests: max_iterations, target size cap, drain reconciliation."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from tests.conftest import make_experiment, make_session

from app.models import Session
from app.models.enums import ExperimentStatus, SessionStatus


# ---------------------------------------------------------------------------
# max_iterations stop condition
# ---------------------------------------------------------------------------


def test_loop_stops_when_max_iterations_reached(db_factory) -> None:
    """loop() must stop and set status=done when current iteration >= max_iterations."""
    Sm = db_factory
    db = Sm()
    s = make_session(db, status=SessionStatus.running, max_iterations=3)

    for i in range(1, 4):
        make_experiment(db, session=s, iteration=i, status=ExperimentStatus.kept)

    with (
        patch("app.tasks.loop.SessionLocal", Sm),
        patch("app.tasks.loop.chain") as chain_mock,
    ):
        from app.tasks.loop import loop

        out = loop.run(s.id)

    assert out["skip"] is True
    assert out["reason"] == "max_iterations_reached"
    chain_mock.assert_not_called()

    db.expire_all()
    assert db.get(Session, s.id).status == SessionStatus.complete


def test_loop_continues_when_under_max_iterations(db_factory) -> None:
    """loop() must enqueue the chain when iteration count is below max_iterations."""
    Sm = db_factory
    db = Sm()
    s = make_session(db, status=SessionStatus.running, max_iterations=5)

    for i in range(1, 3):
        make_experiment(db, session=s, iteration=i, status=ExperimentStatus.kept)

    with (
        patch("app.tasks.loop.SessionLocal", Sm),
        patch("app.tasks.loop.chain") as chain_mock,
    ):
        from app.tasks.loop import loop

        out = loop.run(s.id)

    assert out.get("enqueued") is True
    chain_mock.assert_called_once()


def test_loop_unlimited_when_max_iterations_zero(db_factory) -> None:
    """max_iterations=0 means unlimited — loop must not stop on iteration count."""
    Sm = db_factory
    db = Sm()
    s = make_session(db, status=SessionStatus.running, max_iterations=0)

    for i in range(1, 10):
        make_experiment(db, session=s, iteration=i, status=ExperimentStatus.kept)

    with (
        patch("app.tasks.loop.SessionLocal", Sm),
        patch("app.tasks.loop.chain") as chain_mock,
    ):
        from app.tasks.loop import loop

        out = loop.run(s.id)

    assert out.get("enqueued") is True
    chain_mock.assert_called_once()


# ---------------------------------------------------------------------------
# _read_target size cap
# ---------------------------------------------------------------------------


def _make_fake_settings(tmp_path: Path) -> MagicMock:
    fake = MagicMock()
    fake.target_max_chars = 200_000
    fake.worktree_root = str(tmp_path / "wt")
    return fake


def test_read_target_truncates_large_file(tmp_path: Path) -> None:
    """_read_target must truncate files exceeding target_max_chars."""
    big_file = tmp_path / "big.md"
    big_file.write_text("x" * 300_000, encoding="utf-8")

    from app.agent import context as ctx_mod

    with patch.object(ctx_mod, "get_settings", return_value=_make_fake_settings(tmp_path)):
        result = ctx_mod._read_target(str(tmp_path), "big.md")

    assert result[:200_000] == "x" * 200_000
    assert "TRUNCATED" in result
    assert "300000" in result


def test_read_target_does_not_truncate_small_file(tmp_path: Path) -> None:
    """_read_target must return the full content for files within the cap."""
    small_file = tmp_path / "small.md"
    content = "hello world\n" * 100
    small_file.write_text(content, encoding="utf-8")

    from app.agent import context as ctx_mod

    with patch.object(ctx_mod, "get_settings", return_value=_make_fake_settings(tmp_path)):
        result = ctx_mod._read_target(str(tmp_path), "small.md")

    assert result == content
    assert "TRUNCATED" not in result


# ---------------------------------------------------------------------------
# Drain reconciliation in _propose_again
# ---------------------------------------------------------------------------


def test_propose_again_marks_draining_when_tips_over_budget(db_factory) -> None:
    """_propose_again must set session.status=draining when the retry tips
    tokens_used over token_cap_session, before loop.py gets another chance."""
    Sm = db_factory
    db = Sm()

    # tokens_used=850, token_cap_session=1000, remaining=150.
    # Set token_cap_iter=100 so max_output=min(100,4000)=100.
    # estimate_tokens mocked to 0: 0+100 <= 150 → guard passes.
    # LLMResult returns 200 tokens total: 850+200=1050 >= 1000 → draining.
    s = make_session(
        db,
        status=SessionStatus.running,
        token_cap_session=1000,
        tokens_used=850,
    )
    s.token_cap_iter = 100
    db.commit()
    db.refresh(s)

    exp = make_experiment(db, session=s, iteration=1)

    from app.agent.context import PromptContext
    from app.agent.llm import LLMResult

    fake_result = LLMResult(
        text="--- a\n+++ b\n@@ -1 +1 @@\n-old\n+new\n",
        input_tokens=100,
        output_tokens=100,
        model="dummy",
    )
    fake_ctx = PromptContext(system="sys", user="usr")

    with (
        patch("app.tasks.apply_edit.build_context", return_value=fake_ctx),
        patch("app.tasks.apply_edit.estimate_tokens", return_value=0),
        patch(
            "app.tasks.apply_edit.ProposerClient.complete",
            return_value=fake_result,
        ),
    ):
        from app.tasks.apply_edit import _propose_again

        _propose_again(db, s, exp, hint="retry hint")

    db.expire_all()
    updated = db.get(Session, s.id)
    assert updated.tokens_used == 1050  # 850 + 200
    assert updated.status == SessionStatus.draining
