"""decide — idempotent commit-or-revert + journal + worktree prune + budget check.

Triggered as a fresh Celery task by:
  - POST /experiments/{id}/review   (human approve/reject)
  - score (when review_mode=auto_approve or improvements_only auto-rejects)
  - stale_reviews Beat task (auto-reject on timeout)

The state transition is guarded at the DB level: we do a conditional UPDATE
that only fires when status='awaiting_review'. This makes decide safe under
Celery retries / duplicate delivery: only the first caller transitions the row.

After the transition, decide:
  1. Merges the experiment branch into the session branch on approve.
  2. On reject, resets the experiment worktree back to parent_commit so the
     filesystem checkout reflects the reverted state (branch still exists as a
     journal record).
  2. Appends a `decided` journal record carrying outcome + rejection_comment.
  3. Prunes worktrees of experiments older than worktree_prune_window
     (filesystem checkout removed; object store + journal retained).
  4. Promotes session to `draining` if tokens_used >= token_cap_session
     (drain policy: in-flight finishes, no new iteration starts).
  5. Re-enqueues `loop` so the next iteration can fire.
"""
from __future__ import annotations

import logging
from pathlib import Path

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.git_service import GitError, GitService
from app.journal import append as journal_append
from app.models import Experiment, Session
from app.models.enums import (
    Decision,
    ExperimentStatus,
    SessionStatus,
)
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


def _prune_old_worktrees(db, session: Session, current_iteration: int) -> int:
    """Remove worktrees older than worktree_prune_window iterations back."""
    threshold = current_iteration - session.worktree_prune_window
    if threshold <= 0:
        return 0

    stale = (
        db.query(Experiment)
        .filter(
            Experiment.session_id == session.id,
            Experiment.iteration < threshold,
            Experiment.worktree_pruned.is_(False),
            Experiment.branch_ref.isnot(None),
            Experiment.status.in_(
                [
                    ExperimentStatus.kept,
                    ExperimentStatus.reverted,
                    ExperimentStatus.failed,
                    ExperimentStatus.duplicate,
                ]
            ),
        )
        .all()
    )
    if not stale:
        return 0

    settings = get_settings()
    gitsvc = GitService(worktree_root=settings.worktree_root)
    repo_path = Path(session.folder_path)
    pruned = 0
    for exp in stale:
        wt_path = settings.worktree_root / f"session-{session.id}" / "exp" / exp.id
        try:
            gitsvc.remove_worktree(repo_path, wt_path)
        except GitError as e:
            logger.warning("worktree prune failed for %s: %s", exp.id, e)
        exp.worktree_pruned = True
        pruned += 1
    db.commit()
    return pruned


@celery_app.task(name="autoresearch.decide", bind=True)
def decide(self, experiment_id: str) -> dict:
    db = SessionLocal()
    try:
        # Atomic idempotency guard: only the first caller transitions the row.
        # We move status out of awaiting_review immediately; everything else is
        # derived from the stored decision.
        updated = (
            db.query(Experiment)
            .filter(
                Experiment.id == experiment_id,
                Experiment.status == ExperimentStatus.awaiting_review,
            )
            .update(
                {Experiment.status: ExperimentStatus.running},
                synchronize_session=False,
            )
        )
        db.commit()

        if updated == 0:
            logger.info("decide(%s): not awaiting_review — no-op", experiment_id)
            return {"experiment_id": experiment_id, "noop": True}

        exp = db.get(Experiment, experiment_id)
        if exp is None:
            return {"experiment_id": experiment_id, "noop": True, "reason": "missing after update"}

        session = db.get(Session, exp.session_id)
        if session is None:
            logger.error("decide(%s): session %s vanished", experiment_id, exp.session_id)
            return {"experiment_id": experiment_id, "noop": True, "reason": "session missing"}

        decision = exp.decision  # set by score / review endpoint / stale Beat
        if decision is None:
            logger.error("decide(%s): no decision recorded; failing experiment", experiment_id)
            exp.status = ExperimentStatus.failed
            db.commit()
            return {"experiment_id": experiment_id, "noop": True, "reason": "no decision"}

        # ---- approve path: merge exp branch into session branch ---------
        approved = decision == Decision.approved
        if approved:
            try:
                gitsvc = GitService(worktree_root=get_settings().worktree_root)
                if exp.branch_ref:
                    gitsvc.merge_into_session(
                        Path(session.folder_path),
                        session.id,
                        exp.branch_ref,
                        f"keep exp-{exp.iteration} (Δ{exp.score_delta:+.2f})"
                        if exp.score_delta is not None
                        else f"keep exp-{exp.iteration}",
                    )
                exp.status = ExperimentStatus.kept
                exp.kept = True
            except GitError as e:
                logger.error("decide(%s): merge failed: %s", experiment_id, e)
                exp.status = ExperimentStatus.failed
                exp.kept = False
                db.commit()
                journal_append(
                    session.id,
                    "decided",
                    {
                        "experiment_id": exp.id,
                        "iteration": exp.iteration,
                        "decision": decision.value,
                        "outcome": "failed",
                        "reason": f"merge failed: {e}",
                    },
                )
                _enqueue_loop(session.id)
                return {"experiment_id": experiment_id, "outcome": "failed"}
        else:
            # Revert: reset the experiment worktree back to parent_commit.
            exp.status = ExperimentStatus.reverted
            exp.kept = False
            if exp.parent_commit:
                try:
                    settings = get_settings()
                    gitsvc = GitService(worktree_root=settings.worktree_root)
                    wt_path = settings.worktree_root / f"session-{session.id}" / "exp" / exp.id
                    gitsvc.reset_hard(wt_path, exp.parent_commit)
                except GitError as e:
                    logger.error("decide(%s): reset_hard failed: %s", experiment_id, e)
                    exp.status = ExperimentStatus.failed
                    db.commit()
                    journal_append(
                        session.id,
                        "decided",
                        {
                            "experiment_id": exp.id,
                            "iteration": exp.iteration,
                            "decision": decision.value,
                            "outcome": "failed",
                            "reason": f"revert failed: {e}",
                        },
                    )
                    _enqueue_loop(session.id)
                    return {"experiment_id": experiment_id, "outcome": "failed"}

        db.commit()
        db.refresh(exp)
        db.refresh(session)

        journal_append(
            session.id,
            "decided",
            {
                "experiment_id": exp.id,
                "iteration": exp.iteration,
                "decision": decision.value,
                "outcome": exp.status.value,
                "rejection_comment": exp.rejection_comment,
                "score_delta": exp.score_delta,
                "tokens_used_session": session.tokens_used,
            },
        )

        # ---- worktree prune ---------------------------------------------
        pruned = _prune_old_worktrees(db, session, exp.iteration)
        if pruned:
            journal_append(session.id, "worktrees_pruned", {"count": pruned})

        # ---- token budget drain check -----------------------------------
        if session.tokens_used >= session.token_cap_session:
            if session.status == SessionStatus.running:
                session.status = SessionStatus.draining
                db.commit()
                journal_append(
                    session.id,
                    "session_draining",
                    {"reason": "token_cap_session reached", "tokens": session.tokens_used},
                )

        # ---- re-enqueue loop --------------------------------------------
        _enqueue_loop(session.id)

        return {
            "experiment_id": experiment_id,
            "outcome": exp.status.value,
            "decision": decision.value,
            "kept": exp.kept,
        }
    finally:
        db.close()


def _enqueue_loop(session_id: str) -> None:
    try:
        celery_app.send_task("autoresearch.loop", args=[session_id])
    except Exception as e:
        logger.warning("loop not yet registered; session %s: %s", session_id, e)
