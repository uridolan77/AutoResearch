"""POST /experiments/{id}/review and /skip — 409 idempotency, decide enqueue."""
from __future__ import annotations

from unittest.mock import patch

from fastapi.testclient import TestClient
from tests.conftest import make_experiment, make_session

from app.models import Experiment, Run
from app.models.enums import Decision, ExperimentStatus


def _client(Sm):
    """Build a TestClient that uses the per-test SQLite via the get_db override."""
    from app.core.db import get_db
    from app.main import app

    def _override():
        s = Sm()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_db] = _override
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def test_approve_succeeds_and_enqueues_decide(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db)
    exp = make_experiment(db, s)

    with patch(
        "app.api.routes.experiments.celery_app.send_task"
    ) as send_task:
        for client in _client(Sm):
            r = client.post(
                f"/experiments/{exp.id}/review",
                json={"decision": "approve"},
            )

    assert r.status_code == 202
    body = r.json()
    assert body["decision"] == "approved"
    assert body["queued_decide"] is True
    send_task.assert_called_once_with("autoresearch.decide", args=[exp.id])

    db.expire_all()
    refreshed = db.get(Experiment, exp.id)
    assert refreshed.decision == Decision.approved
    assert refreshed.rejection_comment is None
    # Status must remain awaiting_review until decide runs.
    assert refreshed.status == ExperimentStatus.awaiting_review


def test_reject_with_comment_persists_truncated(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db)
    exp = make_experiment(db, s)

    long_comment = "x" * 600

    with patch("app.api.routes.experiments.celery_app.send_task"):
        for client in _client(Sm):
            r = client.post(
                f"/experiments/{exp.id}/review",
                json={"decision": "reject", "comment": long_comment},
            )

    # Pydantic enforces max_length=500 on the request body.
    assert r.status_code == 422


def test_reject_with_short_comment_persists(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db)
    exp = make_experiment(db, s)

    with patch("app.api.routes.experiments.celery_app.send_task"):
        for client in _client(Sm):
            r = client.post(
                f"/experiments/{exp.id}/review",
                json={"decision": "reject", "comment": "weakened tier-typing"},
            )

    assert r.status_code == 202
    db.expire_all()
    refreshed = db.get(Experiment, exp.id)
    assert refreshed.decision == Decision.rejected
    assert refreshed.rejection_comment == "weakened tier-typing"


def test_double_submit_returns_409(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db)
    exp = make_experiment(db, s)

    with patch("app.api.routes.experiments.celery_app.send_task"):
        for client in _client(Sm):
            r1 = client.post(
                f"/experiments/{exp.id}/review", json={"decision": "approve"}
            )
            r2 = client.post(
                f"/experiments/{exp.id}/review", json={"decision": "reject"}
            )

    assert r1.status_code == 202
    assert r2.status_code == 409
    assert "decision" in r2.json()["detail"]


def test_review_unknown_experiment_returns_404(db_factory) -> None:
    Sm = db_factory
    with patch("app.api.routes.experiments.celery_app.send_task"):
        for client in _client(Sm):
            r = client.post(
                "/experiments/00000000-0000-0000-0000-000000000000/review",
                json={"decision": "approve"},
            )
    assert r.status_code == 404


def test_skip_endpoint_marks_auto_rejected_timeout(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db)
    exp = make_experiment(db, s)

    with patch("app.api.routes.experiments.celery_app.send_task") as send_task:
        for client in _client(Sm):
            r = client.post(f"/experiments/{exp.id}/skip")

    assert r.status_code == 202
    db.expire_all()
    refreshed = db.get(Experiment, exp.id)
    assert refreshed.decision == Decision.auto_rejected_timeout
    assert refreshed.rejection_comment == "manually skipped"
    send_task.assert_called_once_with("autoresearch.decide", args=[exp.id])


def test_get_experiment_detail_returns_runs_and_rejection_history(db_factory) -> None:
    Sm = db_factory
    db = Sm()
    s = make_session(db)
    old_rejected = make_experiment(
        db,
        s,
        iteration=1,
        status=ExperimentStatus.reverted,
        decision=Decision.rejected,
        rejection_comment="avoid broad rewrite",
    )
    exp = make_experiment(
        db,
        s,
        iteration=2,
        status=ExperimentStatus.awaiting_review,
        score_before=0.1,
        score_after=0.5,
        score_delta=0.4,
    )
    run = Run(
        experiment_id=exp.id,
        worker_id="worker-1",
        stdout_path="/tmp/stdout.log",
        stderr_path="/tmp/stderr.log",
        metric_payload={"score": 0.5},
        exit_code=0,
    )
    db.add(run)
    db.commit()
    db.refresh(exp)

    for client in _client(Sm):
        r = client.get(f"/experiments/{exp.id}")

    assert r.status_code == 200
    body = r.json()
    assert body["id"] == exp.id
    assert body["runs"][0]["stdout_path"] == "/tmp/stdout.log"
    assert body["rejection_history"][0]["id"] == exp.id or body["rejection_history"][0]["id"] == old_rejected.id
    assert any(entry["rejection_comment"] == "avoid broad rewrite" for entry in body["rejection_history"])
