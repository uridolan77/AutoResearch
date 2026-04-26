"""Diff validator pipeline tests."""
from __future__ import annotations

from app.agent.validator import extract_files, validate

DIFF_ONE_FILE = """diff --git a/draft.md b/draft.md
--- a/draft.md
+++ b/draft.md
@@ -1 +1 @@
-Original.
+Revised.
"""

DIFF_TWO_FILES = """diff --git a/draft.md b/draft.md
--- a/draft.md
+++ b/draft.md
@@ -1 +1 @@
-A
+B
diff --git a/notes.md b/notes.md
--- a/notes.md
+++ b/notes.md
@@ -1 +1 @@
-X
+Y
"""

DIFF_PROGRAM_MD = """diff --git a/program.md b/program.md
--- a/program.md
+++ b/program.md
@@ -1 +1 @@
-old
+new
"""

DIFF_DOTENV = """diff --git a/.env b/.env
--- a/.env
+++ b/.env
@@ -1 +1 @@
-A=1
+A=2
"""

DIFF_PEM = """diff --git a/keys/server.pem b/keys/server.pem
--- a/keys/server.pem
+++ b/keys/server.pem
@@ -1 +1 @@
-old
+new
"""

DIFF_NOT_WHITELISTED = """diff --git a/other.md b/other.md
--- a/other.md
+++ b/other.md
@@ -1 +1 @@
-A
+B
"""


def test_extract_files_git_header() -> None:
    assert extract_files(DIFF_ONE_FILE) == ("draft.md",)
    assert extract_files(DIFF_TWO_FILES) == ("draft.md", "notes.md")


def test_extract_files_handles_dev_null_for_creation() -> None:
    diff = """diff --git a/new.md b/new.md
--- /dev/null
+++ b/new.md
@@ -0,0 +1 @@
+hello
"""
    assert extract_files(diff) == ("new.md",)


def test_empty_diff_rejected() -> None:
    r = validate("", max_files_per_diff=1, whitelist=("draft.md",))
    assert not r.ok and "empty" in r.reason


def test_too_many_files_rejected() -> None:
    r = validate(DIFF_TWO_FILES, max_files_per_diff=1, whitelist=("draft.md", "notes.md"))
    assert not r.ok
    assert "2 files" in r.reason


def test_protected_program_md_rejected() -> None:
    r = validate(DIFF_PROGRAM_MD, max_files_per_diff=1, whitelist=("program.md",))
    assert not r.ok
    assert "protected" in r.reason


def test_protected_dotenv_rejected() -> None:
    r = validate(DIFF_DOTENV, max_files_per_diff=1, whitelist=(".env",))
    assert not r.ok
    assert "protected" in r.reason


def test_protected_pem_rejected() -> None:
    r = validate(DIFF_PEM, max_files_per_diff=1, whitelist=("keys/server.pem",))
    assert not r.ok
    assert "protected" in r.reason


def test_not_on_whitelist_rejected() -> None:
    r = validate(DIFF_NOT_WHITELISTED, max_files_per_diff=1, whitelist=("draft.md",))
    assert not r.ok
    assert "whitelist" in r.reason


def test_happy_path_passes() -> None:
    r = validate(DIFF_ONE_FILE, max_files_per_diff=1, whitelist=("draft.md",))
    assert r.ok and r.touched_files == ("draft.md",)


def test_two_files_under_higher_cap_passes() -> None:
    r = validate(DIFF_TWO_FILES, max_files_per_diff=5, whitelist=("draft.md", "notes.md"))
    assert r.ok
