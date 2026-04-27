"""apply_edit — pre-evaluator-cost validation, dedup, and commit.

Runs the validation pipeline before either spending evaluator budget or
mutating any worktree. On validation failure the proposer is re-called with
a retry hint until `session.validation_retry_max` is exhausted; all retries
are charged to tokens_used. On dedup match the experiment is short-circuited
without applying or evaluating.

Successful apply: the diff is written into a fresh experiment worktree off
the session branch and committed. The chain proceeds to run_experiment.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from app.agent import (
    ProposerClient,
    build_context,
    diff_hash,
    estimate_tokens,
    validate,
)
from app.core.config import get_settings
from app.core.db import SessionLocal
from app.git_service import GitError, GitService
from app.journal import append as journal_append
from app.models import Experiment, Session
from app.models.enums import ExperimentStatus, SessionStatus
from app.tasks.celery_app import celery_app
from app.tasks.chain import passthrough, short_circuit

logger = logging.getLogger(__name__)

_FENCE_RE = re.compile(r"```(?:diff)?\s*([\s\S]*?)```", re.IGNORECASE)


def _sanitize_diff(raw: str) -> str:
    """Best-effort extraction of a git-apply-compatible unified diff."""
    if not raw:
        return ""
    text = raw.strip()

    # If the model wrapped the diff in fences, extract the first fenced block.
    m = _FENCE_RE.search(text)
    if m:
        text = m.group(1).strip()

    # Drop leading non-diff chatter.
    lines = text.splitlines()
    start = 0
    for i, line in enumerate(lines):
        if line.startswith("diff --git ") or line.startswith("--- ") or line.startswith("+++ "):
            start = i
            break
    cleaned = "\n".join(lines[start:]).strip()

    # Some models emit hunk bodies without the required leading prefix
    # characters (" ", "+", "-", or "\\"). Fix up by prefixing a space for
    # any line inside a hunk that lacks a prefix.
    out_lines: list[str] = []
    in_hunk = False
    for line in cleaned.splitlines():
        if line.startswith("@@"):
            in_hunk = True
            out_lines.append(line)
            continue
        if line.startswith("diff --git ") or line.startswith("--- ") or line.startswith("+++ ") or line.startswith("index "):
            in_hunk = False
            out_lines.append(line)
            continue
        if in_hunk:
            if line.startswith((" ", "+", "-", "\\")):
                out_lines.append(line)
            else:
                out_lines.append(" " + line)
        else:
            out_lines.append(line)

    cleaned = "\n".join(out_lines).strip()
    return cleaned


def _propose_again(db, session: Session, experiment: Experiment, hint: str) -> int:
    """Call the proposer with a validation hint. Charges tokens. Returns total tokens spent."""
    ctx = build_context(db, session, validation_hint=hint)

    est_input = estimate_tokens(ctx.system + ctx.user)
    max_output = min(session.token_cap_iter, 4000)
    if est_input > session.token_cap_iter:
        raise RuntimeError("retry input exceeds token_cap_iter")
    remaining = session.token_cap_session - session.tokens_used
    if est_input + max_output > remaining:
        raise RuntimeError("retry would exceed remaining session budget")

    result = ProposerClient().complete(
        system=ctx.system,
        user=ctx.user,
        max_output_tokens=max_output,
        temperature=0.3,
    )
    experiment.diff_text = result.text
    experiment.tokens_used = (experiment.tokens_used or 0) + result.total_tokens
    session.tokens_used = (session.tokens_used or 0) + result.total_tokens
    db.commit()
    return result.total_tokens


@celery_app.task(name="autoresearch.apply_edit", bind=True)
def apply_edit(self, ctx: dict[str, Any]) -> dict[str, Any]:
    if ctx.get("done"):
        return ctx

    session_id = ctx["session_id"]
    experiment_id = ctx["experiment_id"]

    db = SessionLocal()
    try:
        session = db.get(Session, session_id)
        experiment = db.get(Experiment, experiment_id)
        if session is None or experiment is None:
            return short_circuit(ctx, "session or experiment missing")

        # When max_files_per_diff==1 enforce exact single-file whitelist.
        # When >1, only the max_files_per_diff count constraint applies.
        whitelist = (session.target_file,) if session.max_files_per_diff == 1 else None
        max_attempts = session.validation_retry_max
        repo_path = Path(session.folder_path)
        settings = get_settings()
        gitsvc = GitService(worktree_root=settings.worktree_root)

        # ---- validation + retry loop -------------------------------------
        last_reason: str | None = None
        for attempt in range(1, max_attempts + 1):
            experiment.validation_attempts = attempt
            db.commit()

            experiment.diff_text = _sanitize_diff(experiment.diff_text or "")
            db.commit()

            v = validate(
                experiment.diff_text or "",
                max_files_per_diff=session.max_files_per_diff,
                whitelist=whitelist,
            )
            if v.ok:
                # Also ensure `git apply` accepts the diff (format + context).
                try:
                    gitsvc.check_diff(repo_path, experiment.diff_text or "")
                    last_reason = None
                    break
                except GitError as e:
                    last_reason = str(e)
                    journal_append(
                        session_id,
                        "validation_failed",
                        {
                            "experiment_id": experiment.id,
                            "attempt": attempt,
                            "reason": last_reason,
                        },
                    )
                    if attempt == max_attempts:
                        break
                    try:
                        _propose_again(
                            db,
                            session,
                            experiment,
                            hint=f"validation failed: {last_reason}",
                        )
                    except RuntimeError as e2:
                        journal_append(
                            session_id,
                            "validation_retry_aborted",
                            {"experiment_id": experiment.id, "reason": str(e2)},
                        )
                        last_reason = str(e2)
                        break
                    continue

            last_reason = v.reason
            journal_append(
                session_id,
                "validation_failed",
                {
                    "experiment_id": experiment.id,
                    "attempt": attempt,
                    "reason": last_reason,
                },
            )
            if attempt == max_attempts:
                break

            try:
                _propose_again(
                    db,
                    session,
                    experiment,
                    hint=f"validation failed: {last_reason}",
                )
            except RuntimeError as e:
                # Token budget hit during retry — stop retrying, fall through to fail.
                journal_append(
                    session_id,
                    "validation_retry_aborted",
                    {"experiment_id": experiment.id, "reason": str(e)},
                )
                last_reason = str(e)
                break

        if last_reason is not None:
            experiment.status = ExperimentStatus.failed
            db.commit()
            journal_append(
                session_id,
                "experiment_failed",
                {
                    "experiment_id": experiment.id,
                    "stage": "validation",
                    "reason": last_reason,
                    "attempts": experiment.validation_attempts,
                },
            )
            # Advance the session: failed experiments should not wedge the loop.
            celery_app.send_task("autoresearch.loop", args=[session_id])
            return short_circuit(ctx, f"validation failed after {experiment.validation_attempts} attempts")

        # ---- deduplication ------------------------------------------------
        h = diff_hash(experiment.diff_text)
        existing = (
            db.query(Experiment)
            .filter(
                Experiment.session_id == session_id,
                Experiment.id != experiment.id,
                Experiment.diff_hash == h,
            )
            .first()
        )
        experiment.diff_hash = h
        if existing is not None:
            experiment.status = ExperimentStatus.duplicate
            db.commit()
            journal_append(
                session_id,
                "duplicate_detected",
                {
                    "experiment_id": experiment.id,
                    "matched_experiment_id": existing.id,
                    "diff_hash": h,
                },
            )
            # Duplicate is a terminal outcome for this iteration; move on.
            celery_app.send_task("autoresearch.loop", args=[session_id])
            return short_circuit(ctx, "duplicate diff")

        # ---- apply diff to a fresh experiment worktree -------------------
        exp_path: Path | None = None
        try:
            exp_branch, exp_path = gitsvc.create_experiment_worktree(
                repo_path, session_id, experiment.id
            )
            parent_sha = gitsvc.head_sha(exp_path)
            gitsvc.apply_diff(exp_path, experiment.diff_text)
            commit_sha = gitsvc.commit_all(exp_path, f"exp-{experiment.iteration}: candidate")
        except GitError as e:
            # Best-effort cleanup: if we created a worktree but failed to apply/commit,
            # remove it so repeated failures don't leak disk.
            if exp_path is not None:
                try:
                    gitsvc.remove_worktree(repo_path, exp_path)
                except Exception:
                    pass
            experiment.status = ExperimentStatus.failed
            db.commit()
            journal_append(
                session_id,
                "experiment_failed",
                {"experiment_id": experiment.id, "stage": "git_apply", "reason": str(e)},
            )
            celery_app.send_task("autoresearch.loop", args=[session_id])
            return short_circuit(ctx, f"git apply failed: {e}")

        experiment.parent_commit = parent_sha
        experiment.experiment_commit = commit_sha
        experiment.branch_ref = exp_branch
        experiment.worktree_path = str(exp_path)
        db.commit()

        journal_append(
            session_id,
            "edit_applied",
            {
                "experiment_id": experiment.id,
                "diff_hash": h,
                "commit": commit_sha,
                "branch": exp_branch,
            },
        )
        return passthrough(ctx, worktree_path=str(exp_path))
    finally:
        db.close()
