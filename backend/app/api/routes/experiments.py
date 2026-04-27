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
import re

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session as DbSession

from app.api.schemas import (
    DiffViewResponse,
    ExperimentDetailResponse,
    RejectionHistoryEntryResponse,
    ReviewRequest,
    ReviewResponse,
    RunSummaryResponse,
    SkipResponse,
)
from app.core.db import get_db
from app.models import Experiment
from app.models.enums import Decision, ExperimentStatus
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/experiments", tags=["experiments"])


def _build_diff_view(diff_text: str | None) -> DiffViewResponse | None:
    if not diff_text:
        return None

    lines = diff_text.splitlines()
    if not lines:
        return None

    old_path: str | None = None
    new_path: str | None = None
    old_lines: list[str] = []
    new_lines: list[str] = []
    in_hunk = False

    for line in lines:
        if line.startswith("--- "):
            old_path = line[4:].strip()
            continue
        if line.startswith("+++ "):
            new_path = line[4:].strip()
            continue
        if line.startswith("@@"):
            in_hunk = True
            continue
        if not in_hunk:
            continue

        if line.startswith("+") and not line.startswith("+++"):
            new_lines.append(line[1:])
        elif line.startswith("-") and not line.startswith("---"):
            old_lines.append(line[1:])
        elif line.startswith(" "):
            content = line[1:]
            old_lines.append(content)
            new_lines.append(content)

    file_path = None
    for candidate in (new_path, old_path):
        if candidate and candidate not in ("/dev/null", "a/dev/null", "b/dev/null"):
            file_path = re.sub(r"^[ab]/", "", candidate)
            break

    return DiffViewResponse(
        file_path=file_path,
        old_text="\n".join(old_lines),
        new_text="\n".join(new_lines),
    )


@router.get("/{experiment_id}", response_model=ExperimentDetailResponse)
def get_experiment(
    experiment_id: str,
    db: DbSession = Depends(get_db),
) -> ExperimentDetailResponse:
    exp = db.get(Experiment, experiment_id)
    if exp is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="experiment not found")

    rejection_rows = (
        db.query(Experiment)
        .filter(
            Experiment.session_id == exp.session_id,
            Experiment.rejection_comment.is_not(None),
        )
        .order_by(Experiment.iteration.desc())
        .limit(5)
        .all()
    )

    return ExperimentDetailResponse(
        id=exp.id,
        session_id=exp.session_id,
        iteration=exp.iteration,
        parent_commit=exp.parent_commit,
        experiment_commit=exp.experiment_commit,
        branch_ref=exp.branch_ref,
        status=exp.status.value,
        diff_text=exp.diff_text,
        diff_view=_build_diff_view(exp.diff_text),
        diff_hash=exp.diff_hash,
        validation_attempts=exp.validation_attempts,
        score_before=exp.score_before,
        score_after=exp.score_after,
        score_delta=exp.score_delta,
        tokens_used=exp.tokens_used,
        decision=exp.decision.value if exp.decision else None,
        rejection_comment=exp.rejection_comment,
        kept=exp.kept,
        worktree_pruned=exp.worktree_pruned,
        created_at=exp.created_at.isoformat() if exp.created_at else None,
        runs=[
            RunSummaryResponse(
                id=run.id,
                worker_id=run.worker_id,
                start_at=run.start_at.isoformat() if run.start_at else None,
                end_at=run.end_at.isoformat() if run.end_at else None,
                stdout_path=run.stdout_path,
                stderr_path=run.stderr_path,
                metric_payload=run.metric_payload,
                exit_code=run.exit_code,
            )
            for run in exp.runs
        ],
        rejection_history=[
            RejectionHistoryEntryResponse(
                id=row.id,
                iteration=row.iteration,
                rejection_comment=row.rejection_comment or "",
                decision=row.decision.value if row.decision else None,
                created_at=row.created_at.isoformat() if row.created_at else None,
            )
            for row in rejection_rows
        ],
    )


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
