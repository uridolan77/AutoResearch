"""Git worktree management for autoresearch sessions.

One worktree per experiment, branched off a per-session branch. Workflow:
    session_start: create session branch + base worktree
    per experiment: create exp worktree off session branch
    on keep:    commit in exp worktree, merge into session branch
    on revert:  reset --hard in exp worktree (worktree retained for journal)
    on prune:   remove worktree filesystem checkout (object store kept)
"""
from __future__ import annotations

import logging
import shlex
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


class GitError(RuntimeError):
    pass


# Autoresearch worktree commits are mechanical journal records of what the
# agent tried. They are not human-authored work and are intentionally unsigned —
# signing is reserved for human commits to the platform repo itself.
_UNSIGNED = ["-c", "commit.gpgsign=false", "-c", "tag.gpgsign=false"]


def _run(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    full = [*_UNSIGNED, *args]
    logger.debug("git %s (cwd=%s)", shlex.join(full), cwd)
    try:
        result = subprocess.run(
            ["git", *full],
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
        )
    except subprocess.CalledProcessError as e:
        raise GitError(
            f"git {' '.join(args)} failed (exit {e.returncode}): {e.stderr.strip()}"
        ) from e
    return result.stdout.strip()


class GitService:
    """Wrapper around git CLI for worktree-per-experiment isolation."""

    def __init__(self, worktree_root: Path) -> None:
        self.worktree_root = Path(worktree_root)
        self.worktree_root.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ repo

    def ensure_repo(self, repo_path: Path) -> None:
        repo_path = Path(repo_path)
        if not (repo_path / ".git").exists():
            repo_path.mkdir(parents=True, exist_ok=True)
            _run(["init", "-b", "main"], cwd=repo_path)
            # Required for first commit / for `git worktree add` to work cleanly
            try:
                _run(["config", "user.email", "autoresearch@localhost"], cwd=repo_path)
                _run(["config", "user.name", "autoresearch"], cwd=repo_path)
            except GitError:
                pass
            # An empty repo can't host worktrees; create a root commit if none exist.
            try:
                _run(["rev-parse", "HEAD"], cwd=repo_path)
            except GitError:
                gitkeep = repo_path / ".autoresearch-init"
                gitkeep.write_text("autoresearch session marker\n")
                _run(["add", ".autoresearch-init"], cwd=repo_path)
                _run(["commit", "-m", "autoresearch: initial commit"], cwd=repo_path)

    def head_sha(self, repo_path: Path) -> str:
        return _run(["rev-parse", "HEAD"], cwd=Path(repo_path))

    def current_branch(self, repo_path: Path) -> str:
        return _run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=Path(repo_path))

    # -------------------------------------------------------- session branch

    def create_session_branch(self, repo_path: Path, session_id: str) -> tuple[str, Path]:
        """Create `session-{id}` branch and a base worktree at worktree_root/session-{id}.

        Returns (branch_name, base_worktree_path).
        """
        repo_path = Path(repo_path)
        branch = f"session-{session_id}"
        base_worktree = self.worktree_root / branch
        if base_worktree.exists():
            raise GitError(f"session worktree already exists: {base_worktree}")
        base = self.current_branch(repo_path)
        if base == "HEAD":
            base = self.head_sha(repo_path)
        _run(["worktree", "add", "-b", branch, str(base_worktree), base], cwd=repo_path)
        return branch, base_worktree

    # --------------------------------------------------------- exp worktree

    def create_experiment_worktree(
        self,
        repo_path: Path,
        session_id: str,
        experiment_id: str,
    ) -> tuple[str, Path]:
        """Create a worktree for one experiment off the session branch."""
        repo_path = Path(repo_path)
        session_branch = f"session-{session_id}"
        exp_branch = f"exp-{session_id}-{experiment_id}"
        exp_path = self.worktree_root / session_branch / "exp" / experiment_id
        exp_path.parent.mkdir(parents=True, exist_ok=True)
        _run(
            ["worktree", "add", "-b", exp_branch, str(exp_path), session_branch],
            cwd=repo_path,
        )
        return exp_branch, exp_path

    # -------------------------------------------------------- mutate / keep

    def apply_diff(self, worktree_path: Path, diff_text: str) -> None:
        """Apply a unified diff into the given worktree using `git apply`."""
        worktree_path = Path(worktree_path)
        proc = subprocess.run(
            ["git", "apply", "--whitespace=nowarn", "-"],
            cwd=worktree_path,
            input=diff_text,
            text=True,
            capture_output=True,
        )
        if proc.returncode != 0:
            raise GitError(f"git apply failed: {proc.stderr.strip()}")

    def commit_all(self, worktree_path: Path, message: str) -> str:
        worktree_path = Path(worktree_path)
        _run(["add", "-A"], cwd=worktree_path)
        _run(["commit", "-m", message, "--allow-empty"], cwd=worktree_path)
        return self.head_sha(worktree_path)

    def reset_hard(self, worktree_path: Path, ref: str = "HEAD") -> None:
        _run(["reset", "--hard", ref], cwd=Path(worktree_path))
        _run(["clean", "-fdx"], cwd=Path(worktree_path))

    def merge_into_session(
        self, repo_path: Path, session_id: str, exp_branch: str, message: str
    ) -> str:
        """Fast-forward (or merge) the experiment branch into the session branch.

        We perform the merge in the session base worktree to avoid HEAD races.
        """
        repo_path = Path(repo_path)
        session_branch = f"session-{session_id}"
        session_worktree = self.worktree_root / session_branch
        _run(
            ["merge", "--no-ff", "-m", message, exp_branch],
            cwd=session_worktree,
        )
        return self.head_sha(session_worktree)

    # --------------------------------------------------------------- prune

    def remove_worktree(self, repo_path: Path, worktree_path: Path) -> None:
        """Remove a worktree's filesystem checkout. Object store is retained."""
        repo_path = Path(repo_path)
        worktree_path = Path(worktree_path)
        try:
            _run(["worktree", "remove", "--force", str(worktree_path)], cwd=repo_path)
        except GitError:
            # Already gone or never registered. Fall back to a manual rmtree.
            if worktree_path.exists():
                import shutil

                shutil.rmtree(worktree_path, ignore_errors=True)
            _run(["worktree", "prune"], cwd=repo_path)

    def prune_dangling(self, repo_path: Path) -> None:
        _run(["worktree", "prune"], cwd=Path(repo_path))

    # --------------------------------------------------------------- diff

    def diff_for_commit(self, worktree_path: Path, ref: str = "HEAD") -> str:
        return _run(["show", "--no-color", ref], cwd=Path(worktree_path))
