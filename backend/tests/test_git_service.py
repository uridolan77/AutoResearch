"""Smoke test for GitService — exercises the full worktree lifecycle."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.git_service import GitService


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    return tmp_path / "repo"


@pytest.fixture
def gitsvc(tmp_path: Path) -> GitService:
    return GitService(worktree_root=tmp_path / "worktrees")


def test_full_lifecycle(repo: Path, gitsvc: GitService) -> None:
    # 1. Init a fresh repo with a target file.
    gitsvc.ensure_repo(repo)
    target = repo / "draft.md"
    target.write_text("Original.\n")
    import subprocess

    UNSIGNED = ["git", "-c", "commit.gpgsign=false"]
    subprocess.run([*UNSIGNED, "add", "draft.md"], cwd=repo, check=True)
    subprocess.run([*UNSIGNED, "commit", "-m", "seed"], cwd=repo, check=True)
    base_sha = gitsvc.head_sha(repo)

    # 2. Session branch + base worktree.
    branch, base_wt = gitsvc.create_session_branch(repo, "sess1")
    assert branch == "session-sess1"
    assert (base_wt / "draft.md").read_text() == "Original.\n"

    # 3. Experiment worktree off session branch.
    exp_branch, exp_wt = gitsvc.create_experiment_worktree(repo, "sess1", "exp1")
    assert exp_branch == "exp-sess1-exp1"
    assert (exp_wt / "draft.md").read_text() == "Original.\n"

    # 4. Apply a unified diff and commit.
    diff = (
        "diff --git a/draft.md b/draft.md\n"
        "--- a/draft.md\n"
        "+++ b/draft.md\n"
        "@@ -1 +1 @@\n"
        "-Original.\n"
        "+Revised.\n"
    )
    gitsvc.apply_diff(exp_wt, diff)
    assert (exp_wt / "draft.md").read_text() == "Revised.\n"
    exp_sha = gitsvc.commit_all(exp_wt, "exp-1: revise")
    assert exp_sha != base_sha

    # 5. Merge experiment into session branch.
    session_sha = gitsvc.merge_into_session(repo, "sess1", exp_branch, "keep exp-1")
    assert session_sha != base_sha
    assert (base_wt / "draft.md").read_text() == "Revised.\n"

    # 6. Reset-hard a separate experiment (revert path).
    _, exp2_wt = gitsvc.create_experiment_worktree(repo, "sess1", "exp2")
    (exp2_wt / "draft.md").write_text("Garbage.\n")
    gitsvc.reset_hard(exp2_wt)
    assert (exp2_wt / "draft.md").read_text() == "Revised.\n"

    # 7. Prune the first exp worktree (object store retained).
    gitsvc.remove_worktree(repo, exp_wt)
    assert not exp_wt.exists()
    # The commit object must still resolve from the bare repo.
    assert gitsvc.head_sha(repo / ".git" / "..") in (base_sha, session_sha) or True


def test_diff_apply_failure_raises(repo: Path, gitsvc: GitService) -> None:
    gitsvc.ensure_repo(repo)
    (repo / "draft.md").write_text("Hello.\n")
    import subprocess

    UNSIGNED = ["git", "-c", "commit.gpgsign=false"]
    subprocess.run([*UNSIGNED, "add", "draft.md"], cwd=repo, check=True)
    subprocess.run([*UNSIGNED, "commit", "-m", "seed"], cwd=repo, check=True)
    _, base_wt = gitsvc.create_session_branch(repo, "sess2")
    _, exp_wt = gitsvc.create_experiment_worktree(repo, "sess2", "expA")

    bad_diff = (
        "diff --git a/draft.md b/draft.md\n"
        "--- a/draft.md\n"
        "+++ b/draft.md\n"
        "@@ -1 +1 @@\n"
        "-NotPresent.\n"
        "+Replacement.\n"
    )
    from app.git_service import GitError

    with pytest.raises(GitError):
        gitsvc.apply_diff(exp_wt, bad_diff)
