"""stale_reviews — hourly Beat task that auto-rejects abandoned reviews.

Without this, an experiment that lands in `awaiting_review` and never gets
human attention would clog the session indefinitely. The session-level
`review_timeout_hours` (default 48) caps how long a review can sit before
the platform makes a decision on the human's behalf.

Auto-rejected experiments get a synthetic rejection_comment (v3 loose-end
fix) so the rejection-feedback context block stays informative — the agent
understands the human walked away rather than getting silence.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from app.core.db import SessionLocal
from app.models import Experiment, Session
from app.models.enums import Decision, ExperimentStatus
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="autoresearch.stale_reviews", bind=True)
def stale_reviews(self) -> dict:
    """Scan for awaiting_review experiments past their session's timeout.

    For each:
      - decision = auto_rejected_timeout
      - rejection_comment = synthetic ("review timeout (Nh)")
      - send autoresearch.decide as a fresh task

    decide is itself idempotent (status=='awaiting_review' guard), so a
    duplicate fire from a slow Beat tick is safe.
    """
    db = SessionLocal()
    swept = 0
    try:
        # Join through Session for review_timeout_hours; SQLite doesn't
        # support per-row interval predicates cleanly, so we filter in Python
        # after fetching the candidate set. The set is small in practice
        # (one row per stuck experiment).
        candidates = (
            db.query(Experiment, Session)
            .join(Session, Experiment.session_id == Session.id)
            .filter(Experiment.status == ExperimentStatus.awaiting_review)
            .all()
        )

        now = datetime.now(timezone.utc)
        for exp, sess in candidates:
            # exp.created_at is naive UTC from server_default=func.now() on SQLite;
            # treat as UTC to compare with the timezone-aware `now`.
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

            # decide is idempotent; safe even if a parallel review already moved it.
            celery_app.send_task("autoresearch.decide", args=[exp.id])
            swept += 1

        return {"swept": swept}
    finally:
        db.close()
