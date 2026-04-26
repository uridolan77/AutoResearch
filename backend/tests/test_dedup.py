"""Diff deduplication tests."""
from __future__ import annotations

from app.agent.dedup import diff_hash, normalise_diff


_DIFF_A = """diff --git a/draft.md b/draft.md
--- a/draft.md
+++ b/draft.md
@@ -1 +1 @@
-Original.
+Revised.
"""

# Same logical edit, different line numbers + extra blank lines.
_DIFF_A_PRIME = """diff --git a/draft.md b/draft.md
--- a/draft.md
+++ b/draft.md
@@ -10 +10 @@

-Original.
+Revised.

"""

_DIFF_B = """diff --git a/draft.md b/draft.md
--- a/draft.md
+++ b/draft.md
@@ -1 +1 @@
-Original.
+Different.
"""


def test_normalise_strips_headers() -> None:
    n = normalise_diff(_DIFF_A)
    assert "@@" not in n
    assert "diff --git" not in n
    assert "---" not in n
    assert "+++" not in n


def test_same_edit_different_line_numbers_hashes_identically() -> None:
    assert diff_hash(_DIFF_A) == diff_hash(_DIFF_A_PRIME)


def test_different_edits_hash_differently() -> None:
    assert diff_hash(_DIFF_A) != diff_hash(_DIFF_B)


def test_hash_is_stable_across_calls() -> None:
    assert diff_hash(_DIFF_A) == diff_hash(_DIFF_A)
