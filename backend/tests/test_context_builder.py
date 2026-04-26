"""Context builder — verifies the prompt structure, journal lines, and the
Things-not-to-try block are wired correctly."""
from __future__ import annotations

import uuid
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.agent.context import build_context
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
def db_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'ctx.db'}", future=True)
    Base.metadata.create_all(engine)
    Sm = sessionmaker(bind=engine, future=True)
    db = Sm()
    yield db
    db.close()


def _make_session(db, tmp_path: Path) -> Session:
    target = tmp_path / "draft.md"
    target.write_text("Hello, world.\n")

    ev = Evaluator(
        id=str(uuid.uuid4()),
        name="judge",
        type=EvaluatorType.llm_judge,
        config={"judge_model": "gpt-4o-mini", "score_range": [0, 100]},
        metric_name="quality",
        direction=MetricDirection.maximize,
        timeout_s=120,
        baseline_required=True,
        network_mode=NetworkMode.bridge,
    )
    db.add(ev)
    db.commit()

    s = Session(
        name="t",
        folder_path=str(tmp_path),
        target_file="draft.md",
        program_md="## Goal\nMake it better.\n",
        evaluator_id=ev.id,
        wall_clock_budget_s=60,
        token_cap_session=10_000,
        token_cap_iter=2_000,
        max_files_per_diff=1,
        review_mode=ReviewMode.always,
        status=SessionStatus.running,
    )
    db.add(s)
    db.commit()
    db.refresh(s)
    return s


def test_first_iteration_has_no_journal_or_rejections(db_session, tmp_path) -> None:
    s = _make_session(db_session, tmp_path)
    ctx = build_context(db_session, s)
    assert "Make it better." in ctx.user
    assert "Hello, world." in ctx.user
    assert "(no prior experiments)" in ctx.user
    assert "(no prior rejections)" in ctx.user
    assert "Iteration: 1" in ctx.user


def test_journal_summary_lists_recent_outcomes(db_session, tmp_path) -> None:
    s = _make_session(db_session, tmp_path)
    for i in range(1, 4):
        e = Experiment(
            session_id=s.id,
            iteration=i,
            status=ExperimentStatus.kept if i == 1 else ExperimentStatus.reverted,
            score_delta=0.5 if i == 1 else -0.2,
            kept=(i == 1),
        )
        db_session.add(e)
    db_session.commit()
    ctx = build_context(db_session, s)
    assert "iter   1: KEPT" in ctx.user
    assert "iter   2: REVERTED" in ctx.user
    assert "Iteration: 4" in ctx.user


def test_rejection_comments_appear_in_things_not_to_try(db_session, tmp_path) -> None:
    s = _make_session(db_session, tmp_path)
    e = Experiment(
        session_id=s.id,
        iteration=1,
        status=ExperimentStatus.reverted,
        decision=Decision.rejected,
        rejection_comment="weakened the Firewall tier-typing; do not collapse W/K into kcal",
    )
    db_session.add(e)
    db_session.commit()
    ctx = build_context(db_session, s)
    assert "Firewall tier-typing" in ctx.user
    assert "Things not to try" in ctx.user


def test_validation_hint_block_appears_when_provided(db_session, tmp_path) -> None:
    s = _make_session(db_session, tmp_path)
    ctx = build_context(db_session, s, validation_hint="diff touches 2 files")
    assert "Prior attempt this iteration was rejected" in ctx.user
    assert "diff touches 2 files" in ctx.user
