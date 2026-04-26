"""Evaluator type → implementation class lookup.

Used by run_experiment to instantiate the right evaluator for a session.
"""
from __future__ import annotations

from app.evaluators.base import Evaluator
from app.evaluators.command import CommandEvaluator
from app.evaluators.llm_judge import LLMJudgeEvaluator
from app.models import Evaluator as EvaluatorRow
from app.models.enums import EvaluatorType

_REGISTRY: dict[EvaluatorType, type[Evaluator]] = {
    EvaluatorType.command: CommandEvaluator,
    EvaluatorType.llm_judge: LLMJudgeEvaluator,
    # EvaluatorType.python is Phase 2.
}


def build_evaluator(row: EvaluatorRow, secrets: dict[str, str] | None = None) -> Evaluator:
    impl = _REGISTRY.get(row.type)
    if impl is None:
        raise NotImplementedError(
            f"Evaluator type {row.type!r} not implemented in Phase 1"
        )
    return impl(row, secrets=secrets)
