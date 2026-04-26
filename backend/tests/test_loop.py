"""loop — pause/drain/stop guards + the v3 token-budget escape fix."""
from __future__ import annotations

from unittest.mock import patch

from tests.conftest import make_session

from app.models import Session
from app.models.enums import SessionStatus


def test_loop_skips_when_paused(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db, status=SessionStatus.paused)

    with (
        patch("app.tasks.loop.SessionLocal", Sm),
        patch("app.tasks.loop.chain") as chain_mock,
    ):
        from app.tasks.loop import loop

        out = loop.run(s.id)

    assert out["skip"] is True
    assert "paused" in out["reason"]
    chain_mock.assert_not_called()


def test_loop_skips_when_stopped(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db, status=SessionStatus.stopped)

    with (
        patch("app.tasks.loop.SessionLocal", Sm),
        patch("app.tasks.loop.chain") as chain_mock,
    ):
        from app.tasks.loop import loop

        out = loop.run(s.id)

    assert out["skip"] is True
    chain_mock.assert_not_called()


def test_loop_drains_when_token_budget_exhausted(db_factory) -> None:
    """v3 loose-end fix: validation-retry token burn cannot escape the cap
    because loop checks tokens_used >= token_cap_session at entry."""
    Sm = db_factory
    db = Sm()
    s = make_session(db, token_cap_session=1000, tokens_used=1100)

    with (
        patch("app.tasks.loop.SessionLocal", Sm),
        patch("app.tasks.loop.chain") as chain_mock,
    ):
        from app.tasks.loop import loop

        out = loop.run(s.id)

    assert out["skip"] is True
    assert out["reason"] == "token_cap_session reached"
    chain_mock.assert_not_called()

    db.expire_all()
    assert db.get(Session, s.id).status == SessionStatus.draining


def test_loop_enqueues_chain_when_running_and_under_budget(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db, status=SessionStatus.running, tokens_used=100)

    with (
        patch("app.tasks.loop.SessionLocal", Sm),
        patch("app.tasks.loop.chain") as chain_mock,
    ):
        from app.tasks.loop import loop

        out = loop.run(s.id)

    assert out["enqueued"] is True
    chain_mock.assert_called_once()
    chain_mock.return_value.apply_async.assert_called_once()


def test_loop_skips_unknown_session(db_factory) -> None:
    Sm = db_factory
    with (
        patch("app.tasks.loop.SessionLocal", Sm),
        patch("app.tasks.loop.chain") as chain_mock,
    ):
        from app.tasks.loop import loop

        out = loop.run("nonexistent")

    assert out["skip"] is True
    assert out["reason"] == "missing"
    chain_mock.assert_not_called()
