"""Journal append/read/tail tests."""
from __future__ import annotations

from pathlib import Path

import pytest

from app.journal import journal as journal_mod


@pytest.fixture(autouse=True)
def isolate_data_dir(tmp_path: Path, monkeypatch) -> None:
    """Redirect get_settings().data_dir to a tmp dir for each test."""
    from app.core import config as cfg

    cfg.get_settings.cache_clear()
    monkeypatch.setenv("AR_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("AR_WORKTREE_ROOT", str(tmp_path / "wt"))
    monkeypatch.setenv("AR_SECRET_KEY", "x" * 44)  # not used here
    yield
    cfg.get_settings.cache_clear()


def test_append_and_read_round_trip() -> None:
    journal_mod.append("sess1", "plan_started", {"experiment_id": "e1", "iteration": 1})
    journal_mod.append("sess1", "scored", {"experiment_id": "e1", "delta": 0.5})
    rows = journal_mod.read_all("sess1")
    assert [r["kind"] for r in rows] == ["plan_started", "scored"]
    assert rows[0]["experiment_id"] == "e1"
    assert rows[1]["delta"] == 0.5


def test_tail_returns_last_n() -> None:
    for i in range(7):
        journal_mod.append("sess2", "scored", {"i": i})
    tail = journal_mod.tail("sess2", 3)
    assert len(tail) == 3
    assert [r["i"] for r in tail] == [4, 5, 6]


def test_separate_sessions_dont_collide() -> None:
    journal_mod.append("a", "scored", {"v": 1})
    journal_mod.append("b", "scored", {"v": 2})
    assert journal_mod.read_all("a")[0]["v"] == 1
    assert journal_mod.read_all("b")[0]["v"] == 2


def test_read_all_empty_for_unknown_session() -> None:
    assert journal_mod.read_all("never_used") == []
