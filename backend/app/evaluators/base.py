"""Evaluator interface — the grep-able metric layer.

Each evaluator takes a worktree (folder containing the candidate state) and
returns a single scalar plus the raw payload that produced it. Side effects
are limited to whatever the evaluator does inside its own sandbox.

Phase 1 ships CommandEvaluator (Docker) and LLMJudgeEvaluator (in-process).
PythonEvaluator is Phase 2.

The agent never sees evaluator config, output, or implementation. Only the
final scalar feeds back into the next-iteration context (via score_delta).
"""
from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path

from app.models import Evaluator as EvaluatorRow


@dataclass
class EvaluatorResult:
    score: float
    metric_payload: dict
    stdout: str
    stderr: str
    exit_code: int

    # Tokens spent inside the evaluator itself (only LLMJudgeEvaluator >0).
    # Charged to session.tokens_used so judge spend is visible in the budget.
    tokens_used: int = 0


class EvaluatorError(RuntimeError):
    pass


class Evaluator(abc.ABC):
    """Abstract evaluator. Implementations: CommandEvaluator, LLMJudgeEvaluator."""

    def __init__(self, row: EvaluatorRow, secrets: dict[str, str] | None = None) -> None:
        self.row = row
        self.config = row.config
        self.secrets = secrets or {}

    @abc.abstractmethod
    def evaluate(self, worktree_path: Path) -> EvaluatorResult: ...
