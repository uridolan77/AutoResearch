"""stale_reviews — hourly Beat task that auto-rejects abandoned reviews.

Without this, an experiment that lands in `awaiting_review` and never gets
human attention would clog the session indefinitely. The session-level
`review_timeout_hours` (default 48) caps how long a review can sit before
the platform makes a decision on the human's behalf.

Auto-rejected experiments get a synthetic rejection_comment (v3 loose-end
fix) so the rejection-feedback context block stays informative — the agent
understands the human walked away rather than getting silence.

Also recovers experiments stuck in `deciding` status (worker-death scenario)
by rolling them back to `awaiting_review` after DECIDING_STUCK_MINUTES.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.core.db import SessionLocal
from app.models import Experiment, Session
from app.models.enums import Decision, ExperimentStatus
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)

# Experiments stuck in `deciding` for longer than this are rolled back.
DECIDING_STUCK_MINUTES = 30


@celery_app.task(name="autoresearch.stale_reviews", bind=True)
def stale_reviews(self) -> dict:
    """Scan for awaiting_review experiments past their session's timeout.

    For each:
      - decision = auto_rejected_timeout
      - rejection_comment = synthetic ("review timeout (Nh)")
      - send autoresearch.decide as a fresh task

    Also rolls back any experiments that have been in `deciding` status for
    more than DECIDING_STUCK_MINUTES (worker-death recovery).

    decide is itself idempotent (status=='awaiting_review' guard), so a
    duplicate fire from a slow Beat tick is safe.
    """
    db = SessionLocal()
    swept = 0
    recovered = 0
    try:
        # --- auto-reject stale awaiting_review experiments -----------------
        candidates = (
            db.query(Experiment, Session)
            .join(Session, Experiment.session_id == Session.id)
            .filter(Experiment.status == ExperimentStatus.awaiting_review)
            .all()
        )

        now = datetime.now(timezone.utc)
        for exp, sess in candidates:
            created = exp.created_at
            if created.tzinfo is None:
                created = created.replace(tzinfo=timezone.utc)
            age = now - created
            if age < timedelta(hours=sess.review_timeout_hours):
                continue

            exp.decision = Decision.auto_rejected_timeout
            exp.rejection_comment = (
                f"auto-rejected: review timeout ({sess.review_timeout_hours}h)"
            )
            db.commit()

            celery_app.send_task("autoresearch.decide", args=[exp.id])
            swept += 1

        # --- recover experiments stuck in `deciding` (worker-death rollback) -
        deciding_candidates = (
            db.query(Experiment)
            .filter(Experiment.status == ExperimentStatus.deciding)
            .all()
        )
        stuck_threshold = timedelta(minutes=DECIDING_STUCK_MINUTES)
        for exp in deciding_candidates:
            updated_at = exp.updated_at
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            age = now - updated_at
            if age < stuck_threshold:
                continue
            logger.warning(
                "stale_reviews: experiment %s stuck in deciding for %s; rolling back to awaiting_review",
                exp.id,
                age,
            )
            exp.status = ExperimentStatus.awaiting_review
            db.commit()
            recovered += 1

        return {"swept": swept, "recovered": recovered}
    finally:
        db.close()
