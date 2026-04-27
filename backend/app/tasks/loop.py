"""loop — orchestration gate. Decides whether to re-enqueue another iteration.

Runs as a fresh task (not part of the chain). Enqueued by `decide` after
each experiment outcome. Its job is to enforce all session-level stop
conditions in one place:

    1. session.status not in {running, idle}              -> stop
    2. tokens_used >= token_cap_session                   -> drain + stop
    3. wall_clock_budget_s elapsed since session start    -> stop
    4. max_iterations reached (0 = unlimited)             -> stop
    5. otherwise                                          -> enqueue plan
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

from celery import chain

from app.core.db import SessionLocal
from app.journal import append as journal_append
from app.models import Experiment, Session
from app.models.enums import SessionStatus
from app.tasks.celery_app import celery_app

logger = logging.getLogger(__name__)


@celery_app.task(name="autoresearch.loop", bind=True)
def loop(self, session_id: str) -> dict:
    db = SessionLocal()
    try:
        session = db.get(Session, session_id)
        if session is None:
            return {"session_id": session_id, "skip": True, "reason": "missing"}

        # ---- (1) session-status guard -----------------------------------
        if session.status not in (SessionStatus.running, SessionStatus.idle):
            logger.info(
                "loop(%s): status=%s — not enqueueing", session_id, session.status.value
            )
            return {
                "session_id": session_id,
                "skip": True,
                "reason": f"status={session.status.value}",
            }

        # ---- (2) session-level token budget ceiling --------------------
        # plan.py's per-call check stops a single LLM call from blowing the
        # cap, but validation retries during apply_edit can still burn budget
        # without ever calling decide. Re-checking here closes the loophole.
        if session.tokens_used >= session.token_cap_session:
            session.status = SessionStatus.draining
            db.commit()
            journal_append(
                session_id,
                "session_draining",
                {
                    "reason": "token_cap_session reached at loop entry",
                    "tokens": session.tokens_used,
                    "cap": session.token_cap_session,
                },
            )
            return {
                "session_id": session_id,
                "skip": True,
                "reason": "token_cap_session reached",
            }

        # ---- (3) wall-clock budget ------------------------------------
        created = session.created_at
        if created.tzinfo is None:
            created = created.replace(tzinfo=timezone.utc)
        elapsed_s = (datetime.now(timezone.utc) - created).total_seconds()
        if elapsed_s >= session.wall_clock_budget_s:
            session.status = SessionStatus.complete
            db.commit()
            journal_append(
                session_id,
                "session_stopped",
                {
                    "reason": "wall_clock_budget_exhausted",
                    "elapsed_s": round(elapsed_s),
                    "budget_s": session.wall_clock_budget_s,
                },
            )
            return {
                "session_id": session_id,
                "skip": True,
                "reason": "wall_clock_budget_exhausted",
            }

        # ---- (4) max_iterations cap ------------------------------------
        if session.max_iterations > 0:
            current_iteration = (
                db.query(Experiment.iteration)
                .filter(Experiment.session_id == session_id)
                .order_by(Experiment.iteration.desc())
                   .limit(1)
                   .scalar()
            ) or 0
            if current_iteration >= session.max_iterations:
                session.status = SessionStatus.complete
                db.commit()
                journal_append(
                    session_id,
                    "session_stopped",
                    {
                        "reason": "max_iterations_reached",
                        "iteration": current_iteration,
                        "max_iterations": session.max_iterations,
                    },
                )
                return {
                    "session_id": session_id,
                    "skip": True,
                    "reason": "max_iterations_reached",
                }

        # ---- (5) enqueue next iteration via the chain -------------------
        from app.tasks.apply_edit import apply_edit
        from app.tasks.plan import plan
        from app.tasks.run_experiment import on_chain_error, run_experiment
        from app.tasks.score import score

        chain(
            plan.s(session_id),
            apply_edit.s(),
            run_experiment.s(),
            score.s(),
        ).apply_async(link_error=on_chain_error.s())

        return {"session_id": session_id, "enqueued": True}
    finally:
        db.close()
