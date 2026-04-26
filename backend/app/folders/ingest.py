from __future__ import annotations

import re
import subprocess
from pathlib import Path

from app.core.config import get_settings
from app.git_service import GitService
from app.models.enums import EvaluatorType


_URL_RE = re.compile(r"^(https?://|git@|ssh://)")


def _is_url(s: str) -> bool:
    return bool(_URL_RE.search(s.strip()))


def _run_git(args: list[str], cwd: Path | None = None) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True)


def ingest_folder(path_or_url: str) -> tuple[str, bool, str]:
    """Return (folder_path, is_git_clone, original)."""
    original = path_or_url.strip()
    if not original:
        raise ValueError("path_or_url is empty")

    settings = get_settings()

    if _is_url(original):
        dest = settings.data_dir / "repos"
        dest.mkdir(parents=True, exist_ok=True)
        repo_dir = dest / f"repo-{abs(hash(original))}"
        if not repo_dir.exists():
            _run_git(["clone", "--depth", "1", original, str(repo_dir)])
        return str(repo_dir), True, original

    p = Path(original)
    if not p.exists():
        raise ValueError(f"path does not exist: {p}")

    gitsvc = GitService(worktree_root=settings.worktree_root)
    gitsvc.ensure_repo(p)
    return str(p), False, original


def suggest_targets(folder_path: str) -> list[dict]:
    """Return a shortlist of targets with suggested evaluator types."""
    root = Path(folder_path)
    if not root.exists():
        return []

    out: list[dict] = []

    # Prefer docs for LLMJudge.
    docs_dir = root / "docs"
    md_files: list[Path] = []
    if docs_dir.exists() and docs_dir.is_dir():
        md_files = sorted(docs_dir.rglob("*.md"))[:10]
    if not md_files:
        md_files = sorted(root.rglob("*.md"))[:10]
    for p in md_files[:5]:
        rel = p.relative_to(root).as_posix()
        out.append(
            {
                "target_file": rel,
                "suggested_evaluator_type": EvaluatorType.llm_judge.value,
                "rationale": "markdown/doc target (LLMJudgeEvaluator)",
            }
        )

    # Suggest a code target for CommandEvaluator.
    for p in sorted(root.rglob("*.py"))[:200]:
        rel = p.relative_to(root).as_posix()
        if rel.startswith(".git/"):
            continue
        out.append(
            {
                "target_file": rel,
                "suggested_evaluator_type": EvaluatorType.command.value,
                "rationale": "python source target (CommandEvaluator)",
            }
        )
        break

    return out

