"""decide — idempotency, approve, reject, prune, drain."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.conftest import make_experiment, make_session

from app.models import Experiment, Session
from app.models.enums import (
    Decision,
    ExperimentStatus,
    SessionStatus,
)


def test_double_call_is_a_noop_after_first_decision(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db)
    exp = make_experiment(
        db,
        s,
        decision=Decision.approved,
        score_delta=1.5,
        branch_ref=f"exp-{s.id}-x",
    )

    with (
        patch("app.tasks.decide.SessionLocal", Sm),
        patch("app.tasks.decide._enqueue_loop") as enq,
        patch("app.tasks.decide.GitService") as git_cls,
    ):
        git_cls.return_value = MagicMock()
        from app.tasks.decide import decide

        first = decide.run(exp.id)
        second = decide.run(exp.id)

    assert first["outcome"] == "kept"
    assert second.get("noop") is True
    # loop is enqueued exactly once for the real transition.
    assert enq.call_count == 1


def test_approve_merges_and_marks_kept(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db)
    exp = make_experiment(
        db,
        s,
        decision=Decision.approved,
        score_delta=2.0,
        branch_ref=f"exp-{s.id}-y",
    )

    with (
        patch("app.tasks.decide.SessionLocal", Sm),
        patch("app.tasks.decide._enqueue_loop"),
        patch("app.tasks.decide.GitService") as git_cls,
    ):
        gitsvc = MagicMock()
        git_cls.return_value = gitsvc
        from app.tasks.decide import decide

        out = decide.run(exp.id)

    assert out["outcome"] == "kept"
    db.expire_all()
    refreshed = db.get(Experiment, exp.id)
    assert refreshed.status == ExperimentStatus.kept
    assert refreshed.kept is True
    gitsvc.merge_into_session.assert_called_once()


def test_reject_marks_reverted_without_merge(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db)
    exp = make_experiment(
        db,
        s,
        decision=Decision.rejected,
        rejection_comment="weakened the tier-typing",
        score_delta=-0.5,
    )

    with (
        patch("app.tasks.decide.SessionLocal", Sm),
        patch("app.tasks.decide._enqueue_loop"),
        patch("app.tasks.decide.GitService") as git_cls,
    ):
        gitsvc = MagicMock()
        git_cls.return_value = gitsvc
        from app.tasks.decide import decide

        out = decide.run(exp.id)

    assert out["outcome"] == "reverted"
    db.expire_all()
    refreshed = db.get(Experiment, exp.id)
    assert refreshed.status == ExperimentStatus.reverted
    assert refreshed.kept is False
    gitsvc.merge_into_session.assert_not_called()


def test_drain_triggered_when_token_cap_reached(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db, token_cap_session=1000, tokens_used=1000)
    exp = make_experiment(
        db,
        s,
        decision=Decision.approved,
        branch_ref=f"exp-{s.id}-z",
    )

    with (
        patch("app.tasks.decide.SessionLocal", Sm),
        patch("app.tasks.decide._enqueue_loop"),
        patch("app.tasks.decide.GitService") as git_cls,
    ):
        git_cls.return_value = MagicMock()
        from app.tasks.decide import decide

        decide.run(exp.id)

    db.expire_all()
    refreshed_session = db.get(Session, s.id)
    assert refreshed_session.status == SessionStatus.draining


def test_no_decision_recorded_marks_failed(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db)
    exp = make_experiment(db, s, decision=None)  # bug or race — no decision

    with (
        patch("app.tasks.decide.SessionLocal", Sm),
        patch("app.tasks.decide._enqueue_loop"),
        patch("app.tasks.decide.GitService") as git_cls,
    ):
        git_cls.return_value = MagicMock()
        from app.tasks.decide import decide

        out = decide.run(exp.id)

    assert out["noop"] is True
    db.expire_all()
    assert db.get(Experiment, exp.id).status == ExperimentStatus.failed
