"""Score task routing — verifies improvements_only inverts correctly
(auto-rejects on non-positive delta) per the v3 wording fix, and that the
auto-rejection synthetic comment is populated."""
from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.models import Evaluator, Experiment, Session
from app.models.enums import (
    Decision,
    EvaluatorType,
    ExperimentStatus,
    MetricDirection,
    NetworkMode,
    ReviewMode,
    SessionStatus,
)


@pytest.fixture
def db_engine_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'score.db'}", future=True)
    Base.metadata.create_all(engine)
    Sm = sessionmaker(bind=engine, future=True)
    yield Sm
    engine.dispose()


def _make(db, *, mode: ReviewMode, direction: MetricDirection) -> tuple[Session, Experiment]:
    ev = Evaluator(
        id=str(uuid.uuid4()),
        name="e",
        type=EvaluatorType.command,
        config={},
        metric_name="m",
        direction=direction,
        timeout_s=60,
        baseline_required=True,
        network_mode=NetworkMode.none,
    )
    db.add(ev)
    db.commit()

    s = Session(
        name="s",
        folder_path="/tmp/x",
        target_file="draft.md",
        program_md="x",
        evaluator_id=ev.id,
        wall_clock_budget_s=60,
        token_cap_session=10_000,
        token_cap_iter=1_000,
        max_files_per_diff=1,
        review_mode=mode,
        status=SessionStatus.running,
    )
    db.add(s)
    db.commit()
    db.refresh(s)

    e = Experiment(
        session_id=s.id,
        iteration=1,
        status=ExperimentStatus.scored,
        diff_text="diff",
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return s, e


def test_improvements_only_auto_rejects_on_zero_delta(db_engine_session) -> None:
    Sm = db_engine_session
    db = Sm()
    s, e = _make(db, mode=ReviewMode.improvements_only, direction=MetricDirection.maximize)

    with (
        patch("app.tasks.score.SessionLocal", Sm),
        patch("app.tasks.score._enqueue_decide") as enq,
    ):
        from app.tasks.score import score
        ctx = {
            "session_id": s.id,
            "experiment_id": e.id,
            "score": 50.0,  # delta = 0 because no prior kept; treated as no improvement
        }
        # Run the task directly (bypass Celery dispatch).
        out = score.run(ctx)

    db.expire_all()
    refreshed = db.get(Experiment, e.id)
    assert refreshed.decision == Decision.auto_rejected_no_improvement
    assert refreshed.rejection_comment is not None
    assert "no improvement" in refreshed.rejection_comment
    assert "Δ" in refreshed.rejection_comment
    assert refreshed.status == ExperimentStatus.awaiting_review
    assert out["auto_rejected"] is True
    enq.assert_called_once_with(e.id)


def test_improvements_only_pauses_for_review_on_positive_delta(db_engine_session) -> None:
    Sm = db_engine_session
    db = Sm()
    s, e = _make(db, mode=ReviewMode.improvements_only, direction=MetricDirection.maximize)

    # Plant a prior kept score so delta is computed against it (not equal-to-self).
    prior = Experiment(
        session_id=s.id,
        iteration=0,
        status=ExperimentStatus.kept,
        score_after=40.0,
        kept=True,
    )
    db.add(prior)
    db.commit()

    with (
        patch("app.tasks.score.SessionLocal", Sm),
        patch("app.tasks.score._enqueue_decide") as enq,
    ):
        from app.tasks.score import score
        out = score.run({"session_id": s.id, "experiment_id": e.id, "score": 50.0})

    db.expire_all()
    refreshed = db.get(Experiment, e.id)
    assert refreshed.decision is None  # awaiting human
    assert refreshed.status == ExperimentStatus.awaiting_review
    assert out["awaiting_review"] is True
    enq.assert_not_called()


def test_auto_approve_skips_human_gate(db_engine_session) -> None:
    Sm = db_engine_session
    db = Sm()
    s, e = _make(db, mode=ReviewMode.auto_approve, direction=MetricDirection.maximize)

    with (
        patch("app.tasks.score.SessionLocal", Sm),
        patch("app.tasks.score._enqueue_decide") as enq,
    ):
        from app.tasks.score import score
        out = score.run({"session_id": s.id, "experiment_id": e.id, "score": 7.0})

    db.expire_all()
    refreshed = db.get(Experiment, e.id)
    assert refreshed.decision == Decision.approved
    assert out["auto_approved"] is True
    enq.assert_called_once_with(e.id)


def test_minimize_direction_treats_lower_score_as_improvement(db_engine_session) -> None:
    Sm = db_engine_session
    db = Sm()
    s, e = _make(db, mode=ReviewMode.improvements_only, direction=MetricDirection.minimize)

    prior = Experiment(
        session_id=s.id,
        iteration=0,
        status=ExperimentStatus.kept,
        score_after=10.0,
        kept=True,
    )
    db.add(prior)
    db.commit()

    with (
        patch("app.tasks.score.SessionLocal", Sm),
        patch("app.tasks.score._enqueue_decide") as enq,
    ):
        from app.tasks.score import score
        # Lower is better -> 5 < 10 is an improvement -> pause for review.
        out = score.run({"session_id": s.id, "experiment_id": e.id, "score": 5.0})

    db.expire_all()
    refreshed = db.get(Experiment, e.id)
    assert refreshed.decision is None
    assert out["awaiting_review"] is True
    enq.assert_not_called()
