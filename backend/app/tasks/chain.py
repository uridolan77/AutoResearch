"""Sentinels and shared shape for the ratchet chain.

Each task in the chain receives and returns a dict-shaped context. Using a
plain dict keeps Celery's JSON serialisation simple and lets the chain
short-circuit by setting `done` without the next task having to special-case
its own absence.

Shape:
    {
        "session_id": str,
        "experiment_id": str,
        "iteration": int,
        # Set to True by any upstream task that wants to stop the chain
        # without raising — `done_reason` explains why.
        "done": bool,
        "done_reason": str | None,
    }

`loop` reads `done` after `score` to decide whether to re-enqueue.
"""
from __future__ import annotations

from typing import Any, TypedDict


class ChainContext(TypedDict, total=False):
    session_id: str
    experiment_id: str
    iteration: int
    done: bool
    done_reason: str | None


def passthrough(ctx: dict[str, Any], **updates: Any) -> dict[str, Any]:
    out = dict(ctx)
    out.update(updates)
    return out


def short_circuit(ctx: dict[str, Any], reason: str) -> dict[str, Any]:
    return passthrough(ctx, done=True, done_reason=reason)
