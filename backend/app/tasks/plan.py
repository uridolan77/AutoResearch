"""plan — first task in the chain.

Responsibilities:
  1. Create a new Experiment row (status=pending) with the next iteration #.
  2. Build the proposer context from program.md + target file + journal +
     "Things not to try".
  3. Pre-call token cap check: estimate input tokens; refuse to spend if
     either token_cap_iter or remaining session budget would be exceeded.
  4. Call the proposer (Claude Sonnet 4.5).
  5. Persist tokens_used and the raw diff onto the Experiment row.
  6. Append a `plan_started` journal record.
  7. Hand off to apply_edit via the chain context.

Cost-control short-circuits set ctx["done"]=True so the chain unwinds
without raising.

NB: The session-level token budget check is also enforced at the top of
loop (Days 7-8) so validation-retry burn cannot escape the cap.
"""
from __future__ import annotations

import logging
from typing import Any

from app.agent import ProposerClient, build_context, estimate_tokens
from app.core.db import SessionLocal
from app.journal import append as journal_append
from app.models import Experiment, Session
from app.models.enums import ExperimentStatus, SessionStatus
from app.tasks.celery_app import celery_app
from app.tasks.chain import passthrough, short_circuit

logger = logging.getLogger(__name__)


def _next_iteration(db, session_id: str) -> int:
    last = (
        db.query(Experiment.iteration)
        .filter(Experiment.session_id == session_id)
        .order_by(Experiment.iteration.desc())
        .first()
    )
    return (last[0] + 1) if last else 1


@celery_app.task(name="autoresearch.plan", bind=True)
def plan(self, session_id: str) -> dict[str, Any]:
    db = SessionLocal()
    try:
        session = db.get(Session, session_id)
        if session is None:
            return {"session_id": session_id, "done": True, "done_reason": "session not found"}

        # --- session-status guards (mirrored on `loop`) -------------------
        if session.status not in (SessionStatus.running, SessionStatus.idle):
            return {
                "session_id": session_id,
                "done": True,
                "done_reason": f"session status is {session.status.value}",
            }

        # --- create experiment row -----------------------------------------
        iteration = _next_iteration(db, session_id)
        experiment = Experiment(
            session_id=session_id,
            iteration=iteration,
            status=ExperimentStatus.pending,
        )
        db.add(experiment)
        db.commit()
        db.refresh(experiment)

        ctx_msg = build_context(db, session)

        # --- pre-call token cap check --------------------------------------
        est_input = estimate_tokens(ctx_msg.system + ctx_msg.user)
        max_output = min(session.token_cap_iter, 4000)  # cap per-call output
        est_total = est_input + max_output

        if est_input > session.token_cap_iter:
            experiment.status = ExperimentStatus.failed
            db.commit()
            journal_append(
                session_id,
                "plan_aborted",
                {
                    "experiment_id": experiment.id,
                    "iteration": iteration,
                    "reason": "estimated input exceeds token_cap_iter",
                    "est_input": est_input,
                    "cap": session.token_cap_iter,
                },
            )
            return short_circuit(
                {"session_id": session_id, "experiment_id": experiment.id, "iteration": iteration},
                "input exceeds token_cap_iter",
            )

        remaining_session = session.token_cap_session - session.tokens_used
        if est_total > remaining_session:
            experiment.status = ExperimentStatus.failed
            db.commit()
            journal_append(
                session_id,
                "plan_aborted",
                {
                    "experiment_id": experiment.id,
                    "iteration": iteration,
                    "reason": "estimated total exceeds remaining session budget",
                    "est_total": est_total,
                    "remaining": remaining_session,
                },
            )
            session.status = SessionStatus.draining
            db.commit()
            return short_circuit(
                {"session_id": session_id, "experiment_id": experiment.id, "iteration": iteration},
                "session token budget exhausted",
            )

        # --- proposer call --------------------------------------------------
        proposer = ProposerClient()
        result = proposer.complete(
            system=ctx_msg.system,
            user=ctx_msg.user,
            max_output_tokens=max_output,
            temperature=0.3,
        )

        # --- persist + charge ----------------------------------------------
        experiment.diff_text = result.text
        experiment.tokens_used = result.total_tokens
        session.tokens_used = (session.tokens_used or 0) + result.total_tokens
        db.commit()

        journal_append(
            session_id,
            "plan_started",
            {
                "experiment_id": experiment.id,
                "iteration": iteration,
                "tokens": result.total_tokens,
                "model": result.model,
            },
        )

        return passthrough(
            {"session_id": session_id, "experiment_id": experiment.id, "iteration": iteration}
        )
    finally:
        db.close()
