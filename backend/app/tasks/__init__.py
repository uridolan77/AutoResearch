"""Celery task package — the ratchet chain + state-machine glue.

Chain (composed by `loop`):
    plan -> apply_edit -> run_experiment -> score

The chain TERMINATES at score when status=awaiting_review. Review is a state
machine, not a blocking call: the review endpoint enqueues `decide` as a
fresh task, decide re-enqueues `loop`, loop spawns the next chain.

Auxiliary tasks:
    decide        — idempotent commit-or-revert + journal + prune + budget check
    loop          — gate that decides whether to enqueue another iteration
    stale_reviews — Beat task; auto-rejects abandoned awaiting_review rows
    on_chain_error— link_error handler; marks experiment failed on chain crash
"""
from app.tasks.apply_edit import apply_edit
from app.tasks.celery_app import celery_app
from app.tasks.chain import passthrough, short_circuit
from app.tasks.decide import decide
from app.tasks.loop import loop
from app.tasks.plan import plan
from app.tasks.run_experiment import on_chain_error, run_experiment
from app.tasks.score import score
from app.tasks.stale_reviews import stale_reviews

__all__ = [
    "apply_edit",
    "celery_app",
    "decide",
    "loop",
    "on_chain_error",
    "passthrough",
    "plan",
    "run_experiment",
    "score",
    "short_circuit",
    "stale_reviews",
]
