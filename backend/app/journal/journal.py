"""Append-only JSONL journal — survives process restarts.

One file per session at <data_dir>/sessions/<session_id>/autoresearch.jsonl.
Records are written at well-defined chain transitions:
    plan_started, edit_applied, duplicate_detected, scored,
    decided (kept/reverted/auto_rejected_*), failed.

The journal is the source of truth for restart-survivable state and is the
input to the rejection-feedback context block. It is never pruned.
"""
from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.core.config import get_settings

_lock = threading.Lock()


def _journal_path(session_id: str) -> Path:
    root = get_settings().data_dir / "sessions" / session_id
    root.mkdir(parents=True, exist_ok=True)
    return root / "autoresearch.jsonl"


def append(session_id: str, kind: str, payload: dict[str, Any]) -> None:
    """Append a record. Process-local lock + fsync ensures crash-safe writes."""
    record = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        **payload,
    }
    line = json.dumps(record, separators=(",", ":"), default=str) + "\n"
    path = _journal_path(session_id)
    with _lock:
        with open(path, "a", encoding="utf-8") as f:
            f.write(line)
            f.flush()
            os.fsync(f.fileno())


def read_all(session_id: str) -> list[dict[str, Any]]:
    path = _journal_path(session_id)
    if not path.exists():
        return []
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def tail(session_id: str, n: int) -> list[dict[str, Any]]:
    return read_all(session_id)[-n:]
