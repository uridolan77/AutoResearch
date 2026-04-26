"""run_experiment — dispatch the configured evaluator against the experiment worktree.

Creates a Run row capturing worker_id, timing, exit code, and metric_payload.
Stdout/stderr are persisted to disk under data_dir/sessions/<sid>/runs/<rid>/
so they survive restarts and can be displayed in the review UI.

Crash path (link_error): if this task or any downstream chain task raises
unhandled, on_chain_error marks the experiment failed, journals the reason,
and re-enqueues the loop so a daemon hiccup doesn't wedge the session.
This is the v3 "loose end" fix.
"""
from __future__ import annotations

import logging
import socket
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings
from app.core.db import SessionLocal
from app.evaluators import EvaluatorError, build_evaluator
from app.journal import append as journal_append
from app.models import Evaluator as EvaluatorRow
from app.models import Experiment, Run, Session
from app.models.enums import ExperimentStatus
from app.secrets import SecretError, decrypt_refs
from app.tasks.celery_app import celery_app
from app.tasks.chain import passthrough, short_circuit

logger = logging.getLogger(__name__)


def _run_dir(session_id: str, run_id: str) -> Path:
    p = get_settings().data_dir / "sessions" / session_id / "runs" / run_id
    p.mkdir(parents=True, exist_ok=True)
    return p


@celery_app.task(name="autoresearch.run_experiment", bind=True)
def run_experiment(self, ctx: dict[str, Any]) -> dict[str, Any]:
    if ctx.get("done"):
        return ctx

    session_id = ctx["session_id"]
    experiment_id = ctx["experiment_id"]
    worktree_path = Path(ctx["worktree_path"])

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
            return short_circuit(ctx, "evaluator row missing")

        # Decrypt secret refs at runtime; never logged, never persisted in plaintext.
        try:
            secrets = decrypt_refs(db, evaluator_row.secret_refs or [])
        except SecretError as e:
            experiment.status = ExperimentStatus.failed
            db.commit()
            journal_append(
                session_id,
                "experiment_failed",
                {"experiment_id": experiment_id, "stage": "secrets", "reason": str(e)},
            )
            return short_circuit(ctx, f"secrets: {e}")

        run = Run(
            experiment_id=experiment_id,
            worker_id=socket.gethostname(),
            start_at=datetime.now(timezone.utc),
        )
        db.add(run)
        experiment.status = ExperimentStatus.running
        db.commit()
        db.refresh(run)

        rdir = _run_dir(session_id, run.id)
        stdout_path = rdir / "stdout.txt"
        stderr_path = rdir / "stderr.txt"

        evaluator = build_evaluator(evaluator_row, secrets=secrets)
        try:
            result = evaluator.evaluate(worktree_path)
        except EvaluatorError as e:
            run.end_at = datetime.now(timezone.utc)
            run.exit_code = -1
            run.stderr_path = str(stderr_path)
            stderr_path.write_text(str(e), encoding="utf-8")
            experiment.status = ExperimentStatus.failed
            db.commit()
            journal_append(
                session_id,
                "experiment_failed",
                {"experiment_id": experiment_id, "stage": "evaluator", "reason": str(e)},
            )
            return short_circuit(ctx, f"evaluator: {e}")

        stdout_path.write_text(result.stdout or "", encoding="utf-8")
        stderr_path.write_text(result.stderr or "", encoding="utf-8")

        run.end_at = datetime.now(timezone.utc)
        run.stdout_path = str(stdout_path)
        run.stderr_path = str(stderr_path)
        run.metric_payload = result.metric_payload
        run.exit_code = result.exit_code

        # Charge any tokens the evaluator itself spent (LLMJudge).
        if result.tokens_used:
            session.tokens_used = (session.tokens_used or 0) + result.tokens_used
            experiment.tokens_used = (experiment.tokens_used or 0) + result.tokens_used

        db.commit()

        return passthrough(
            ctx,
            score=result.score,
            run_id=run.id,
        )
    finally:
        db.close()


@celery_app.task(name="autoresearch.on_chain_error", bind=True)
def on_chain_error(self, request, exc, traceback) -> None:
    """link_error handler — marks the in-flight experiment failed on any
    unhandled exception in the chain. Re-enqueueing the loop is the
    responsibility of decide (Days 7-8); for now we just journal and mark.
    """
    args = request.args or []
    ctx = args[0] if args and isinstance(args[0], dict) else {}
    session_id = ctx.get("session_id")
    experiment_id = ctx.get("experiment_id")
    if not (session_id and experiment_id):
        logger.error("on_chain_error: cannot recover ctx; exc=%s", exc)
        return

    db = SessionLocal()
    try:
        exp = db.get(Experiment, experiment_id)
        if exp is not None and exp.status not in (
            ExperimentStatus.kept,
            ExperimentStatus.reverted,
            ExperimentStatus.failed,
            ExperimentStatus.duplicate,
        ):
            exp.status = ExperimentStatus.failed
            db.commit()
        journal_append(
            session_id,
            "experiment_failed",
            {
                "experiment_id": experiment_id,
                "stage": "chain_crash",
                "reason": f"{type(exc).__name__}: {exc}",
            },
        )
    finally:
        db.close()
