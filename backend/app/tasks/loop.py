"""loop — orchestration gate. Decides whether to re-enqueue another iteration.

Runs as a fresh task (not part of the chain). Enqueued by `decide` after
each experiment outcome. Its job is to enforce all session-level stop
conditions in one place:

    1. session.status not in {running, idle}              -> stop
    2. tokens_used >= token_cap_session                   -> drain + stop
       (this is the v3 loose-end fix: validation-retry token burn can't
       escape the cap because plan's per-iter check is not the same as
       the per-session ceiling)
    3. otherwise                                          -> enqueue plan
"""
from __future__ import annotations

import logging

from celery import chain

from app.core.db import SessionLocal
from app.journal import append as journal_append
from app.models import Session
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

        # ---- (2) session-level token budget escape (v3 fix) -------------
        # plan.py's per-call check stops a single LLM call from blowing the
        # cap, but validation retries during apply_edit can still burn budget
        # without ever calling decide (which is normally where draining is
        # detected). Re-checking here closes the loophole.
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

        # ---- (3) enqueue next iteration via the chain -------------------
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
