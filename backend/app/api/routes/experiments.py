"""Experiment review endpoints.

The review gate is a state machine, not a blocking task. The endpoint:
  1. Conditionally updates the experiment row WHERE status='awaiting_review'.
  2. Returns 409 if the conditional update affected 0 rows (already decided,
     missing, or in another state).
  3. Otherwise enqueues `autoresearch.decide` as a fresh Celery task.

`decide` is itself idempotent (its own status guard), so a duplicate submit
that races past the conditional update is also safe.
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.api.schemas import ReviewRequest, ReviewResponse, SkipResponse
from app.core.db import get_db
from app.models import Experiment
from app.models.enums import Decision, ExperimentStatus
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/experiments", tags=["experiments"])


@router.post(
    "/{experiment_id}/review",
    response_model=ReviewResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def submit_review(
    experiment_id: str,
    body: ReviewRequest,
    db: DbSession = Depends(get_db),
) -> ReviewResponse:
    decision = (
        Decision.approved if body.decision == "approve" else Decision.rejected
    )
    comment = (body.comment or "").strip() if decision == Decision.rejected else None

    # Conditional update: only fires if status is awaiting_review.
    # rowcount lets us tell first-write from a no-op race.
    updated = (
        db.query(Experiment)
        .filter(
            Experiment.id == experiment_id,
            Experiment.status == ExperimentStatus.awaiting_review,
            # decision IS NULL closes the double-submit race: review/skip set
            # decision but not status (status is moved later by decide), so
            # status alone isn't a sufficient idempotency guard.
            Experiment.decision.is_(None),
        )
        .update(
            {
                Experiment.decision: decision,
                Experiment.rejection_comment: comment,
            },
            synchronize_session=False,
        )
    )
    db.commit()

    if updated == 0:
        # Either the experiment doesn't exist, or it's already past
        # awaiting_review. Both are 409 from the caller's perspective.
        exists = (
            db.query(Experiment.id)
            .filter(Experiment.id == experiment_id)
            .first()
        )
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="experiment not found",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="experiment is not awaiting review or already has a decision",
        )

    queued = True
    try:
        celery_app.send_task("autoresearch.decide", args=[experiment_id])
    except Exception as e:
        logger.error("decide enqueue failed for %s: %s", experiment_id, e)
        queued = False

    exp = db.get(Experiment, experiment_id)
    return ReviewResponse(
        experiment_id=experiment_id,
        status=exp.status.value,
        decision=decision.value,
        queued_decide=queued,
    )


@router.post(
    "/{experiment_id}/skip",
    response_model=SkipResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def skip_review(
    experiment_id: str,
    db: DbSession = Depends(get_db),
) -> SkipResponse:
    """Force-reject without a comment — manual stale-review resolution.

    Same conditional-update / idempotency model as /review.
    """
    decision = Decision.auto_rejected_timeout
    synthetic = "manually skipped"

    updated = (
        db.query(Experiment)
        .filter(
            Experiment.id == experiment_id,
            Experiment.status == ExperimentStatus.awaiting_review,
            # decision IS NULL closes the double-submit race: review/skip set
            # decision but not status (status is moved later by decide), so
            # status alone isn't a sufficient idempotency guard.
            Experiment.decision.is_(None),
        )
        .update(
            {
                Experiment.decision: decision,
                Experiment.rejection_comment: synthetic,
            },
            synchronize_session=False,
        )
    )
    db.commit()

    if updated == 0:
        exists = (
            db.query(Experiment.id)
            .filter(Experiment.id == experiment_id)
            .first()
        )
        if exists is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="experiment not found",
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="experiment is not awaiting review or already has a decision",
        )

    queued = True
    try:
        celery_app.send_task("autoresearch.decide", args=[experiment_id])
    except Exception as e:
        logger.error("decide enqueue failed for %s: %s", experiment_id, e)
        queued = False

    exp = db.get(Experiment, experiment_id)
    return SkipResponse(
        experiment_id=experiment_id,
        status=exp.status.value,
        decision=decision.value,
        queued_decide=queued,
    )
