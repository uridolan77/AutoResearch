"""Shared pytest fixtures for the backend test suite."""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core.db import Base
from app.models import Evaluator, Experiment, Session
from app.models.enums import (
    EvaluatorType,
    ExperimentStatus,
    MetricDirection,
    NetworkMode,
    ReviewMode,
    SessionStatus,
)


@pytest.fixture
def db_factory(tmp_path: Path):
    """Per-test SQLite engine + sessionmaker."""
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}", future=True)
    Base.metadata.create_all(engine)
    Sm = sessionmaker(bind=engine, future=True)
    yield Sm
    engine.dispose()


@pytest.fixture
def db(db_factory):
    s = db_factory()
    try:
        yield s
    finally:
        s.close()


def make_evaluator(
    db,
    *,
    direction: MetricDirection = MetricDirection.maximize,
    type_: EvaluatorType = EvaluatorType.command,
) -> Evaluator:
    ev = Evaluator(
        id=str(uuid.uuid4()),
        name=f"e-{uuid.uuid4().hex[:6]}",
        type=type_,
        config={"image": "alpine", "command": "true", "metric_regex": "()."},
        metric_name="m",
        direction=direction,
        timeout_s=60,
        baseline_required=True,
        network_mode=NetworkMode.none,
    )
    db.add(ev)
    db.commit()
    db.refresh(ev)
    return ev


def make_session(
    db,
    *,
    folder_path: str = "/tmp/repo",
    target_file: str = "draft.md",
    review_mode: ReviewMode = ReviewMode.always,
    status: SessionStatus = SessionStatus.running,
    token_cap_session: int = 10_000,
    tokens_used: int = 0,
    review_timeout_hours: int = 48,
    worktree_prune_window: int = 10,
    direction: MetricDirection = MetricDirection.maximize,
) -> Session:
    ev = make_evaluator(db, direction=direction)
    s = Session(
        name="t",
        folder_path=folder_path,
        target_file=target_file,
        program_md="## Goal\nMake it better.\n",
        evaluator_id=ev.id,
        wall_clock_budget_s=60,
        token_cap_session=token_cap_session,
        token_cap_iter=2_000,
        max_files_per_diff=1,
        review_mode=review_mode,
        review_timeout_hours=review_timeout_hours,
        worktree_prune_window=worktree_prune_window,
        validation_retry_max=3,
        status=status,
        tokens_used=tokens_used,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def make_experiment(
    db,
    session: Session,
    *,
    iteration: int = 1,
    status: ExperimentStatus = ExperimentStatus.awaiting_review,
    score_before: float | None = None,
    score_after: float | None = None,
    score_delta: float | None = None,
    decision=None,
    rejection_comment: str | None = None,
    branch_ref: str | None = None,
    age_hours: float = 0,
) -> Experiment:
    created = datetime.now(timezone.utc) - timedelta(hours=age_hours)
    e = Experiment(
        session_id=session.id,
        iteration=iteration,
        status=status,
        score_before=score_before,
        score_after=score_after,
        score_delta=score_delta,
        decision=decision,
        rejection_comment=rejection_comment,
        branch_ref=branch_ref,
        diff_text="diff",
        created_at=created,
    )
    db.add(e)
    db.commit()
    db.refresh(e)
    return e
