"""score — final task in the chain.

Reads the score from run_experiment, computes score_delta against the
current best (last kept score, or session baseline), then routes per
review_mode:

    auto_approve      -> directly enqueue decide(approved). Fully autonomous.
    improvements_only -> if score_delta <= 0: enqueue decide with synthetic
                         rejection_comment "auto-rejected: no improvement (Δ…)";
                         else pause for human review.
    always            -> always pause for human review.

When the chain pauses (status=awaiting_review) the chain TERMINATES here.
The review endpoint enqueues `decide` as a fresh task — review is a state
machine, not a blocking call.

NB: the v3 loose-end "synthetic rejection_comment for auto-reject paths" is
fixed here so the rejection-feedback context block stays informative when
auto-reject modes fire.
"""
from __future__ import annotations

import logging
from typing import Any

from app.core.db import SessionLocal
from app.journal import append as journal_append
from app.models import Evaluator as EvaluatorRow
from app.models import Experiment, Session
from app.models.enums import (
    Decision,
    ExperimentStatus,
    MetricDirection,
    ReviewMode,
)
from app.tasks.celery_app import celery_app
from app.tasks.chain import passthrough, short_circuit

logger = logging.getLogger(__name__)


def _baseline_score(db, session: Session) -> float | None:
    """The score to compare against. Last kept experiment's score_after,
    or None if no kept experiments exist yet (first iteration baseline)."""
    last_kept = (
        db.query(Experiment)
        .filter(
            Experiment.session_id == session.id,
            Experiment.status == ExperimentStatus.kept,
        )
        .order_by(Experiment.iteration.desc())
        .first()
    )
    if last_kept is not None and last_kept.score_after is not None:
        return float(last_kept.score_after)
    return None


def _is_improvement(delta: float, direction: MetricDirection) -> bool:
    if direction == MetricDirection.maximize:
        return delta > 0
    return delta < 0


@celery_app.task(name="autoresearch.score", bind=True)
def score(self, ctx: dict[str, Any]) -> dict[str, Any]:
    if ctx.get("done"):
        return ctx

    session_id = ctx["session_id"]
    experiment_id = ctx["experiment_id"]
    raw_score = ctx.get("score")
    if raw_score is None:
        return short_circuit(ctx, "score missing from chain context")

    db = SessionLocal()
    try:
        session = db.get(Session, session_id)
        experiment = db.get(Experiment, experiment_id)
        if session is None or experiment is None:
            return short_circuit(ctx, "session or experiment missing")
        evaluator_row = db.get(EvaluatorRow, session.evaluator_id)
        if evaluator_row is None:
            experiment.status = ExperimentStatus.failed
            db.commit()
            journal_append(
                session_id,
                "experiment_failed",
                {
                    "experiment_id": experiment_id,
                    "stage": "score",
                    "reason": "evaluator row missing",
                },
            )
            celery_app.send_task("autoresearch.loop", args=[session_id])
            return short_circuit(ctx, "evaluator row missing")

        baseline = _baseline_score(db, session)
        score_after = float(raw_score)
        # First-iteration semantics: with no prior kept score, treat the
        # baseline as score_after itself so delta=0 and the experiment is
        # judged purely on the human's reading of the diff/score.
        score_before = baseline if baseline is not None else score_after
        score_delta = score_after - score_before

        experiment.score_before = score_before
        experiment.score_after = score_after
        experiment.score_delta = score_delta
        experiment.status = ExperimentStatus.scored
        db.commit()

        journal_append(
            session_id,
            "scored",
            {
                "experiment_id": experiment_id,
                "score_before": score_before,
                "score_after": score_after,
                "delta": score_delta,
            },
        )

        # ---- review_mode routing ----------------------------------------
        mode = session.review_mode
        direction = evaluator_row.direction

        if mode == ReviewMode.auto_approve:
            experiment.decision = Decision.approved
            experiment.status = ExperimentStatus.awaiting_review
            db.commit()
            _enqueue_decide(experiment_id)
            return passthrough(ctx, awaiting_review=False, auto_approved=True)

        if mode == ReviewMode.improvements_only and not _is_improvement(score_delta, direction):
            experiment.decision = Decision.auto_rejected_no_improvement
            experiment.rejection_comment = (
                f"auto-rejected: no improvement (Δ{score_delta:+.2f})"
            )
            experiment.status = ExperimentStatus.awaiting_review
            db.commit()
            journal_append(
                session_id,
                "auto_rejected",
                {
                    "experiment_id": experiment_id,
                    "reason": "no_improvement",
                    "delta": score_delta,
                },
            )
            _enqueue_decide(experiment_id)
            return passthrough(ctx, awaiting_review=False, auto_rejected=True)

        # All other paths: pause for human review. Chain terminates here.
        experiment.status = ExperimentStatus.awaiting_review
        db.commit()
        journal_append(
            session_id,
            "awaiting_review",
            {
                "experiment_id": experiment_id,
                "delta": score_delta,
            },
        )
        return passthrough(ctx, awaiting_review=True)
    finally:
        db.close()


def _enqueue_decide(experiment_id: str) -> None:
    """Decide is implemented in Days 7-8; this is the seam.

    For now we send the task by name so the Celery dispatcher will route it
    once the task is registered. If the task isn't registered yet (Phase 1
    Days 4-6 only), Celery returns a SendTaskError on send — which we
    swallow with a log line so the score chain doesn't fail.
    """
    try:
        celery_app.send_task("autoresearch.decide", args=[experiment_id])
    except Exception as e:
        logger.warning("decide not yet registered (Days 7-8); experiment %s queued: %s",
                       experiment_id, e)
