from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from app.evaluators.command import CommandEvaluator
from app.evaluators.base import EvaluatorError
from tests.conftest import make_evaluator


def test_validated_worktree_path_accepts_path_inside_root(tmp_path) -> None:
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir(parents=True)
    worktree = worktree_root / "session-1"
    worktree.mkdir()

    with patch("app.evaluators.command.get_settings", return_value=SimpleNamespace(worktree_root=worktree_root)):
        resolved = CommandEvaluator._validated_worktree_path(worktree)

    assert resolved == worktree.resolve()


def test_validated_worktree_path_rejects_escape(tmp_path) -> None:
    worktree_root = tmp_path / "worktrees"
    worktree_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()

    with patch("app.evaluators.command.get_settings", return_value=SimpleNamespace(worktree_root=worktree_root)):
        with pytest.raises(EvaluatorError, match="escapes configured worktree_root"):
            CommandEvaluator._validated_worktree_path(outside)


def test_extract_metric_rejects_path_escape(db_factory, tmp_path) -> None:
    db = db_factory()
    ev = make_evaluator(db)
    ev.config = {
        "image": "alpine",
        "command": "true",
        "metric_source": "file:../../secret.txt",
        "metric_regex": "(\\d+)",
    }
    db.commit()

    evaluator = CommandEvaluator(ev)

    with pytest.raises(EvaluatorError, match="escapes worktree"):
        evaluator._extract_metric("", tmp_path)

    db.close()
