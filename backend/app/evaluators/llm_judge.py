"""LLMJudgeEvaluator — sends target file + rubric to a different-provider LLM.

Config schema:
    {
        "judge_model": "gpt-4o-mini",
        "rubric_path": "evaluators/rubric.md",   # path relative to worktree
        "score_range": [0, 100],
        "target_file": "section.md",             # path relative to worktree
        "max_output_tokens": 200                 # judge response cap
    }

Runs in-process (not in Docker) because the only effect is one outbound API
call to a known endpoint. Tokens spent on the judge are returned in
EvaluatorResult.tokens_used so the score task can charge them to
session.tokens_used.

Decorrelation rule: judge_model must come from a different provider than the
proposer. Default config uses gpt-4o-mini; the proposer is Claude Sonnet 4.5.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from app.agent.llm import JudgeClient, estimate_tokens
from app.evaluators.base import Evaluator, EvaluatorError, EvaluatorResult

logger = logging.getLogger(__name__)


_JUDGE_SYSTEM = """You are an impartial judge scoring a piece of work against a rubric.

Read the rubric and the work, then output a single JSON object:
  {{"score": <number in [{lo}, {hi}]>, "rationale": "<one short sentence>"}}

Scoring rules:
  - Use the full range; do not cluster around the midpoint.
  - Do NOT explain at length — one sentence of rationale is enough.
  - Output JSON ONLY. No prose, no fences."""

# Leave a buffer for the rubric and prompt boilerplate (~2 000 tokens) so we
# don't hit the judge model's context limit on large target files.
_CONTEXT_WINDOW_TOKENS = 120_000
_TARGET_TOKEN_BUDGET = _CONTEXT_WINDOW_TOKENS - 2_000


_SCORE_RE = re.compile(r'"score"\s*:\s*([-+]?\d+(?:\.\d+)?)')


class LLMJudgeEvaluator(Evaluator):
    def evaluate(self, worktree_path: Path) -> EvaluatorResult:
        cfg = self.config

        target_file = cfg.get("target_file")
        rubric_path = cfg.get("rubric_path")
        if not target_file or not rubric_path:
            raise EvaluatorError(
                "LLMJudgeEvaluator config requires 'target_file' and 'rubric_path'"
            )

        score_lo, score_hi = cfg.get("score_range", [0, 100])
        max_output_tokens = int(cfg.get("max_output_tokens", 200))
        judge_model = cfg.get("judge_model")  # may be None — JudgeClient defaults

        target = (worktree_path / target_file).read_text(encoding="utf-8", errors="replace")
        rubric = (worktree_path / rubric_path).read_text(encoding="utf-8", errors="replace")

        system = _JUDGE_SYSTEM.format(lo=score_lo, hi=score_hi)

        # Guard: if the combined payload would exceed the judge model's context
        # window, truncate the target file content with a visible marker so the
        # call still succeeds and the score reflects the visible portion.
        overhead_tokens = estimate_tokens(system + rubric)
        target_budget = _TARGET_TOKEN_BUDGET - overhead_tokens
        if target_budget <= 0:
            raise EvaluatorError(
                "Rubric alone exceeds context window budget; shorten the rubric."
            )
        target_tokens = estimate_tokens(target)
        if target_tokens > target_budget:
            # Truncate by character ratio: chars ≈ tokens * 4
            char_limit = target_budget * 4
            target = target[:char_limit] + "\n\n[TRUNCATED — content exceeded context window]"
            logger.warning(
                "target_file %r truncated from ~%d to ~%d tokens for LLM judge",
                target_file,
                target_tokens,
                target_budget,
            )

        user = (
            f"## Rubric\n\n{rubric}\n\n---\n\n"
            f"## Work to score (`{target_file}`)\n\n{target}\n"
        )

        # Judge runs with its own API key (from env / settings).
        # The OPENAI_API_KEY in self.secrets, if present, takes precedence so
        # operators can isolate judge spend from proposer spend per-session.
        api_key = self.secrets.get("OPENAI_API_KEY") or None
        client = JudgeClient(api_key=api_key, model=judge_model)
        result = client.complete(
            system=system,
            user=user,
            max_output_tokens=max_output_tokens,
            temperature=0.0,
        )

        score, payload = self._parse_score(result.text, score_lo, score_hi)
        return EvaluatorResult(
            score=score,
            metric_payload={
                "judge_model": result.model,
                "judge_response": payload,
                "raw_text": result.text,
            },
            stdout=result.text,
            stderr="",
            exit_code=0,
            tokens_used=result.total_tokens,
        )

    # ------------------------------------------------------------ helpers

    @staticmethod
    def _parse_score(text: str, lo: float, hi: float) -> tuple[float, dict]:
        # Try strict JSON first; fall back to regex.
        try:
            obj = json.loads(text.strip())
            score = float(obj["score"])
        except (json.JSONDecodeError, KeyError, ValueError, TypeError):
            m = _SCORE_RE.search(text)
            if not m:
                raise EvaluatorError(
                    f"judge did not return a parseable score; raw={text[:200]!r}"
                )
            score = float(m.group(1))
            obj = {"score": score, "rationale": "(unparseable rationale)"}

        # Clamp into the declared range — the judge sometimes overshoots.
        score = max(float(lo), min(float(hi), score))
        return score, obj
