"""stale_reviews — Beat task auto-rejects on review_timeout_hours expiry."""
from __future__ import annotations

from unittest.mock import patch

from tests.conftest import make_experiment, make_session

from app.models import Experiment
from app.models.enums import Decision, ExperimentStatus


def test_fresh_awaiting_review_is_not_swept(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db, review_timeout_hours=48)
    exp = make_experiment(
        db, s, status=ExperimentStatus.awaiting_review, age_hours=1
    )

    with (
        patch("app.tasks.stale_reviews.SessionLocal", Sm),
        patch("app.tasks.stale_reviews.celery_app") as ca,
    ):
        from app.tasks.stale_reviews import stale_reviews

        out = stale_reviews.run()

    assert out["swept"] == 0
    ca.send_task.assert_not_called()
    db.expire_all()
    assert db.get(Experiment, exp.id).decision is None


def test_stale_awaiting_review_is_auto_rejected_with_synthetic_comment(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db, review_timeout_hours=48)
    stale = make_experiment(
        db, s, status=ExperimentStatus.awaiting_review, age_hours=72
    )

    with (
        patch("app.tasks.stale_reviews.SessionLocal", Sm),
        patch("app.tasks.stale_reviews.celery_app") as ca,
    ):
        from app.tasks.stale_reviews import stale_reviews

        out = stale_reviews.run()

    assert out["swept"] == 1
    db.expire_all()
    refreshed = db.get(Experiment, stale.id)
    assert refreshed.decision == Decision.auto_rejected_timeout
    assert refreshed.rejection_comment is not None
    assert "review timeout" in refreshed.rejection_comment
    assert "48h" in refreshed.rejection_comment
    ca.send_task.assert_called_once_with(
        "autoresearch.decide", args=[stale.id]
    )


def test_already_decided_is_not_swept(db_factory) -> None:
    """An experiment in a terminal state must not be re-rejected."""
    Sm = db_factory
    db = Sm()
    s = make_session(db, review_timeout_hours=48)
    kept = make_experiment(
        db, s, status=ExperimentStatus.kept, age_hours=72
    )

    with (
        patch("app.tasks.stale_reviews.SessionLocal", Sm),
        patch("app.tasks.stale_reviews.celery_app") as ca,
    ):
        from app.tasks.stale_reviews import stale_reviews

        out = stale_reviews.run()

    assert out["swept"] == 0
    ca.send_task.assert_not_called()
    db.expire_all()
    assert db.get(Experiment, kept.id).decision is None
