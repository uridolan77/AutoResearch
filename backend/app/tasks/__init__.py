"""Celery task package — the ratchet chain.

Days 4-6 (this batch): plan -> apply_edit -> run_experiment -> score
Days 7-8 (next batch):  decide, loop, stale-review Beat task

The chain is composed at the API layer (start endpoint, Days 9-10) via:

    chain(
        plan.s(session_id),
        apply_edit.s(),
        run_experiment.s(),
        score.s(),
    ).apply_async(link_error=on_chain_error.s())

Each task takes (and returns) the dict-shaped ChainContext defined in
app.tasks.chain. Tasks short-circuit by setting ctx['done']=True without
raising, so cost-control / dedup / validation-fail paths unwind cleanly.
"""
from app.tasks.apply_edit import apply_edit
from app.tasks.celery_app import celery_app
from app.tasks.chain import passthrough, short_circuit
from app.tasks.plan import plan
from app.tasks.run_experiment import on_chain_error, run_experiment
from app.tasks.score import score

__all__ = [
    "apply_edit",
    "celery_app",
    "on_chain_error",
    "passthrough",
    "plan",
    "run_experiment",
    "score",
    "short_circuit",
]
