from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from tests.conftest import make_experiment, make_session

from app.core.config import get_settings
from app.models import Evaluator, Experiment
from app.models.enums import ExperimentStatus


def test_settings_requires_secret_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("AR_LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("AR_ANTHROPIC_API_KEY", "dummy")
    monkeypatch.setenv("AR_SECRET_KEY", "")
    get_settings.cache_clear()

    with pytest.raises(ValueError, match="AR_SECRET_KEY"):
        get_settings()


def test_plan_retries_on_iteration_race(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    session = make_session(db)

    # Existing row at iteration=1 forces the first attempt to collide.
    db.add(
        Experiment(
            session_id=session.id,
            iteration=1,
            status=ExperimentStatus.kept,
        )
    )
    db.commit()

    fake_result = SimpleNamespace(text="diff --git a/draft.md b/draft.md", total_tokens=10, model="m")

    with (
        patch("app.tasks.plan.SessionLocal", Sm),
        patch("app.tasks.plan._next_iteration", side_effect=[1, 2]) as next_iter,
        patch("app.tasks.plan.build_context", return_value=SimpleNamespace(system="s", user="u")),
        patch("app.tasks.plan.estimate_tokens", return_value=1),
        patch("app.tasks.plan.ProposerClient") as proposer_cls,
    ):
        proposer_cls.return_value.complete.return_value = fake_result
        from app.tasks.plan import plan

        out = plan.run(session.id)

    assert out["session_id"] == session.id
    assert next_iter.call_count == 2

    db.expire_all()
    rows = (
        db.query(Experiment)
        .filter(Experiment.session_id == session.id)
        .order_by(Experiment.iteration.asc())
        .all()
    )
    assert [r.iteration for r in rows] == [1, 2]


def test_plan_short_circuits_if_iteration_allocation_exhausted(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    session = make_session(db)

    db.add(
        Experiment(
            session_id=session.id,
            iteration=1,
            status=ExperimentStatus.kept,
        )
    )
    db.commit()

    with (
        patch("app.tasks.plan.SessionLocal", Sm),
        patch("app.tasks.plan._next_iteration", side_effect=[1, 1, 1]),
        patch("app.tasks.plan.celery_app.send_task") as send_task,
    ):
        from app.tasks.plan import plan

        out = plan.run(session.id)

    assert out["done"] is True
    assert "unique iteration" in out["done_reason"]
    send_task.assert_called_once_with("autoresearch.loop", args=[session.id])

    db.expire_all()
    # Still only the pre-existing row.
    count = db.query(Experiment).filter(Experiment.session_id == session.id).count()
    assert count == 1


def test_score_fails_fast_when_evaluator_missing(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    session = make_session(db)
    exp = make_experiment(db, session, status=ExperimentStatus.scored)

    ev = db.get(Evaluator, session.evaluator_id)
    assert ev is not None
    db.delete(ev)
    db.commit()

    with (
        patch("app.tasks.score.SessionLocal", Sm),
        patch("app.tasks.score.celery_app.send_task") as send_task,
    ):
        from app.tasks.score import score

        out = score.run({"session_id": session.id, "experiment_id": exp.id, "score": 1.0})

    assert out["done"] is True
    assert out["done_reason"] == "evaluator row missing"

    db.expire_all()
    refreshed = db.get(Experiment, exp.id)
    assert refreshed is not None
    assert refreshed.status == ExperimentStatus.failed
    send_task.assert_called_once_with("autoresearch.loop", args=[session.id])
