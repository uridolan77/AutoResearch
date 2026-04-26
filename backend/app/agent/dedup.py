"""Diff deduplication via SHA256 of a normalised diff.

Normalisation strips hunk headers, file headers, and collapses whitespace
so cosmetic variations (line numbers shifting, blank-line jitter) hash
identically. This catches the common failure mode where the proposer
re-emits the same logical edit with trivial differences.

Phase 2 will add an AST-level semantic hash for Python/JS. Do not implement
that here.
"""
from __future__ import annotations

import hashlib
import re

_HEADER_PREFIXES = ("@@", "---", "+++", "diff --git", "index ")


def normalise_diff(diff_text: str) -> str:
    lines = [
        line for line in diff_text.splitlines()
        if not any(line.startswith(p) for p in _HEADER_PREFIXES)
    ]
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def diff_hash(diff_text: str) -> str:
    return hashlib.sha256(normalise_diff(diff_text).encode("utf-8")).hexdigest()
