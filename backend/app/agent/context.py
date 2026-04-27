"""Context builder for the proposer LLM.

Assembles the per-iteration prompt:

    [program.md]
    [target file contents]
    [Journal — last N experiments, one line each]
    [Things not to try — last 5 rejection comments verbatim]

The "Things not to try" block is capped at 5 entries x 500 chars = 2,500
tokens worst case. Rejection comments stored on the Experiment row are the
source of truth; the journal is a parallel append-only mirror.

When apply_edit retries the proposer after a validation failure, callers
pass `validation_hint` so the next attempt is steered toward a passing diff
rather than re-emitting the same shape.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session as DbSession

from app.core.config import get_settings
from app.models import Experiment, Session
from app.models.enums import Decision, ExperimentStatus
from app.models.experiment import REJECTION_COMMENT_MAX_LEN

JOURNAL_TAIL = 10
REJECTION_TAIL = 5
REJECTION_MAX_CHARS = REJECTION_COMMENT_MAX_LEN

logger = logging.getLogger(__name__)


@dataclass
class PromptContext:
    system: str
    user: str

    @property
    def char_count(self) -> int:
        return len(self.system) + len(self.user)


def _journal_lines(db: DbSession, session_id: str) -> list[str]:
    rows = (
        db.query(Experiment)
        .filter(Experiment.session_id == session_id)
        .order_by(Experiment.iteration.desc())
        .limit(JOURNAL_TAIL)
        .all()
    )
    rows.reverse()
    out: list[str] = []
    for r in rows:
        delta = f"{r.score_delta:+.2f}" if r.score_delta is not None else "  ?  "
        status = r.status.value
        comment = ""
        if r.rejection_comment:
            comment = f'  "{r.rejection_comment[:80]}"'
        out.append(f"  iter {r.iteration:>3}: {status.upper():<14} Δ{delta}{comment}")
    return out


def _things_not_to_try(db: DbSession, session_id: str) -> list[str]:
    rows = (
        db.query(Experiment)
        .filter(
            Experiment.session_id == session_id,
            Experiment.decision.in_([
                Decision.rejected,
                Decision.auto_rejected_no_improvement,
                Decision.auto_rejected_timeout,
            ]),
            Experiment.rejection_comment.isnot(None),
        )
        .order_by(Experiment.iteration.desc())
        .limit(REJECTION_TAIL)
        .all()
    )
    return [r.rejection_comment[:REJECTION_MAX_CHARS] for r in rows]


def _next_iteration(db: DbSession, session_id: str) -> int:
    last = (
        db.query(Experiment.iteration)
        .filter(Experiment.session_id == session_id)
        .order_by(Experiment.iteration.desc())
        .first()
    )
    return (last[0] + 1) if last else 1


def _read_target(folder_path: str, target_file: str, session_id: str | None = None) -> str:
    # Prefer the session worktree so the proposer sees the current committed
    # state of the branch (including all previously kept edits).  Fall back to
    # the bare repo root when the worktree hasn't been created yet.
    base: Path | None = None
    if session_id is not None:
        worktree = Path(get_settings().worktree_root) / f"session-{session_id}"
        if worktree.exists():
            base = worktree
    if base is None:
        base = Path(folder_path)
    p = base / target_file
    if not p.exists():
        return f"<target file missing at {p}>"
    text = p.read_text(encoding="utf-8", errors="replace")
    limit = get_settings().target_max_chars
    if len(text) > limit:
        logger.warning(
            "_read_target: %s is %d chars, truncating to %d", p, len(text), limit
        )
        text = text[:limit] + f"\n[TARGET TRUNCATED: {len(text)} chars total, showing first {limit}]"
    return text


SYSTEM_PROMPT = """You are an autonomous editor running inside an autoresearch ratchet loop.

Each iteration you propose ONE small, reversible improvement to a single target file.
Output a UNIFIED DIFF (git apply format) and nothing else — no prose, no fences.

HARD RULES:
  - Touch ONLY the target file shown below.
  - Maximum {max_files_per_diff} file(s) per diff.
  - Never modify program.md, evaluator configs, .env, or any secret file.
  - Make the smallest change that plausibly moves the metric in the right direction.

FORMAT REQUIREMENTS (must follow exactly):
  - Output must start with: diff --git a/<target_file> b/<target_file>
  - Include --- a/<target_file> and +++ b/<target_file>
  - Include at least one @@ hunk header
  - Do NOT include Markdown fences (```), headings, or explanations.

Your diff will be:
  1. Validated (file count, whitelist, protected paths) — failure costs you a retry.
  2. Hashed and rejected if it duplicates a prior attempt.
  3. Applied, committed in an isolated git worktree, and run through the evaluator.
  4. Reviewed by a human (approve = kept, reject = reverted, with a comment that
     will appear in your next iteration's "Things not to try" block).

Example (structure only; your content must match the real file contents):
diff --git a/<target_file> b/<target_file>
index 0000000..0000000 100644
--- a/<target_file>
+++ b/<target_file>
@@ -1,3 +1,3 @@
-old line
+new line
"""

USER_TEMPLATE = """## program.md (the research direction — you do NOT edit this)

{program_md}

---

## Target file: `{target_file}`

```
{target_contents}
```

---

## Journal — last {journal_tail} experiments

{journal_block}

## Things not to try — last {rej_tail} rejection comments (verbatim)

{rejection_block}

---

## This iteration

Iteration: {iteration}
Allowed files: {allowed_files}
{validation_hint_block}
Output a unified diff for this iteration. Diff only — no explanation."""


def build_context(
    db: DbSession,
    session: Session,
    *,
    validation_hint: str | None = None,
) -> PromptContext:
    journal_lines = _journal_lines(db, session.id)
    rejections = _things_not_to_try(db, session.id)

    journal_block = "\n".join(journal_lines) if journal_lines else "  (no prior experiments)"
    if rejections:
        rejection_block = "\n".join(f"  • \"{c}\"" for c in rejections)
    else:
        rejection_block = "  (no prior rejections)"

    if validation_hint:
        validation_hint_block = (
            f"\nPrior attempt this iteration was rejected by validation: {validation_hint}\n"
            "Do NOT repeat that mistake.\n"
        )
    else:
        validation_hint_block = ""

    system = SYSTEM_PROMPT.format(max_files_per_diff=session.max_files_per_diff)
    user = USER_TEMPLATE.format(
        program_md=session.program_md,
        target_file=session.target_file,
        target_contents=_read_target(session.folder_path, session.target_file, session.id),
        journal_tail=JOURNAL_TAIL,
        journal_block=journal_block,
        rej_tail=REJECTION_TAIL,
        rejection_block=rejection_block,
        iteration=_next_iteration(db, session.id),
        allowed_files=session.target_file,
        validation_hint_block=validation_hint_block,
    )
    return PromptContext(system=system, user=user)
