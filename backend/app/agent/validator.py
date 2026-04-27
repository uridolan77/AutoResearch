"""Pre-evaluator-cost diff validation pipeline.

Runs in apply_edit *before* the diff is written to a worktree or sent through
the evaluator. Failure here is cheap; failure after evaluator spend is not.

Validation rules (in order):
    1. Diff is non-empty.
    2. Diff parses to a known set of file paths.
    3. File count <= max_files_per_diff.
    4. Every touched file is on the editable whitelist.
    5. No touched file matches a protected pattern (program.md, evaluator
       configs, .env, secret files, .git, gitignored entries).

Returns a ValidationResult so callers can decide between retrying the
proposer with a hint and giving up after `validation_retry_max` attempts.
"""
from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from pathlib import PurePosixPath

# Files the agent must never touch. Mirrored in app.secrets.store deny list.
PROTECTED_PATTERNS: tuple[str, ...] = (
    "program.md",
    "PROGRAM.md",
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*.p12",
    "*.pfx",
    "secrets/*",
    "secrets/**",
    "credentials.json",
    "token.json",
    ".netrc",
    "*.secret",
    "id_rsa",
    "id_rsa.*",
    "id_ed25519",
    "id_ed25519.*",
    ".aws/credentials",
    ".git/*",
    ".git/**",
    ".autoresearch/*",
    ".autoresearch/**",
    "evaluator.json",
    "evaluator.yaml",
    "evaluator.yml",
)


@dataclass
class ValidationResult:
    ok: bool
    reason: str | None = None
    touched_files: tuple[str, ...] = ()


# `diff --git a/<path> b/<path>` is the canonical header git emits.
_GIT_HEADER = re.compile(r"^diff --git a/(.+?) b/(.+?)$", re.MULTILINE)
# Fallback: --- a/foo / +++ b/foo for diffs without the `diff --git` header.
_TRIPLE_DASH = re.compile(r"^--- (?:a/)?(.+?)$", re.MULTILINE)
_TRIPLE_PLUS = re.compile(r"^\+\+\+ (?:b/)?(.+?)$", re.MULTILINE)


def extract_files(diff_text: str) -> tuple[str, ...]:
    """Pull out the set of file paths a unified diff touches."""
    files: list[str] = []

    def _append_unique(path: str) -> None:
        if path and path != "/dev/null" and path not in files:
            files.append(path)

    for m in _GIT_HEADER.finditer(diff_text):
        a, b = m.group(1).strip(), m.group(2).strip()
        # Count one logical file per header. For renames prefer destination path.
        if a != b and b != "/dev/null":
            _append_unique(b)
            continue
        _append_unique(a)

    if not files:
        # Fall back to --- / +++ headers if diff --git wasn't present.
        for m in _TRIPLE_DASH.finditer(diff_text):
            p = m.group(1).strip()
            _append_unique(p)
        for m in _TRIPLE_PLUS.finditer(diff_text):
            p = m.group(1).strip()
            _append_unique(p)

    return tuple(files)


def _matches_any(path: str, patterns: tuple[str, ...]) -> bool:
    p = PurePosixPath(path).as_posix()
    name = PurePosixPath(p).name
    for pat in patterns:
        if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(name, pat):
            return True
    return False


def validate(
    diff_text: str,
    *,
    max_files_per_diff: int,
    whitelist: tuple[str, ...] | None,
    extra_protected: tuple[str, ...] = (),
) -> ValidationResult:
    if not diff_text or not diff_text.strip():
        return ValidationResult(False, "diff is empty")

    files = extract_files(diff_text)
    if not files:
        return ValidationResult(False, "no file paths found in diff")

    if len(files) > max_files_per_diff:
        return ValidationResult(
            False,
            f"diff touches {len(files)} files; max allowed is {max_files_per_diff}",
            files,
        )

    protected = PROTECTED_PATTERNS + tuple(extra_protected)
    for f in files:
        if _matches_any(f, protected):
            return ValidationResult(False, f"protected file touched: {f}", files)

    if whitelist is not None:
        whitelist_set = set(whitelist)
        for f in files:
            if f not in whitelist_set:
                return ValidationResult(
                    False,
                    f"file {f!r} is not on the editable whitelist {sorted(whitelist_set)!r}",
                    files,
                )

    return ValidationResult(True, None, files)
