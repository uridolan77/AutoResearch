from __future__ import annotations

from pathlib import Path

from app.agent.context import SYSTEM_PROMPT, USER_TEMPLATE
from app.agent.llm import estimate_tokens


def estimate_iteration_tokens(
    *,
    program_md: str,
    folder_path: str,
    target_file: str,
    max_files_per_diff: int = 1,
    token_cap_iter: int = 100_000,
) -> dict:
    """Dry-run estimate for one iteration. No LLM calls."""
    p = Path(folder_path) / target_file
    if p.exists():
        target_contents = p.read_text(encoding="utf-8", errors="replace")
    else:
        target_contents = f"<target file missing at {p}>"

    system = SYSTEM_PROMPT.format(max_files_per_diff=max_files_per_diff)
    user = USER_TEMPLATE.format(
        program_md=program_md,
        target_file=target_file,
        target_contents=target_contents,
        journal_tail=10,
        journal_block="  (no prior experiments)",
        rej_tail=5,
        rejection_block="  (no prior rejections)",
        iteration=1,
        allowed_files=target_file,
        validation_hint_block="",
    )

    est_input = estimate_tokens(system + user)
    max_output = min(int(token_cap_iter), 4000)
    return {
        "estimated_input_tokens": est_input,
        "estimated_max_output_tokens": max_output,
        "estimated_total_tokens": est_input + max_output,
    }

