"""
prepare.py — IO contract for the AutoResearch-style book loop.

This file is the equivalent of Karpathy's prepare.py: the agent never edits
it. It owns chapter loading, anchor parsing, machinery extraction, footnote
validation, metrics, and atomic section replacement. Everything else in the
loop reads chapters and writes edits through this module.

A section is identified by (chapter_id, anchor_id), e.g. ("ch12", "12.0.2"),
or for unnumbered headings, a slug, e.g. ("ch12", "notes-on-this-refinement").

Heading conventions handled:
    # **Chapter 5**                              (chapter title; level 0)
    # **The Genesis Engine ...**                 (chapter subtitle; level 0)
    ## **5.1 The Conversion**                    (numbered section)
    ## §10.1 — The Debt Is Navigational ...      (section-symbol style)
    ## The Morning the Shirt Was Chosen          (unnumbered)
    ### **The Metastable Field**                 (sub-section)
    ### §13.1.1 The Training Loop Is Not a Canon (numbered sub-section)
"""

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BOOK_DIR = ROOT / "book"
BASELINES_DIR = ROOT / ".baselines"
JOURNAL_PATH = ROOT / "journal.jsonl"
CHANGELOG_PATH = ROOT / "CHANGELOG.md"
PROGRAM_PATH = ROOT / "program.md"
BASELINE_META_PATH = ROOT / "baseline.json"


# ---------- chapter ids ----------

CHAPTER_FILE_RE = re.compile(r"^Chapter\s+(\d+)\b", re.IGNORECASE)


def chapter_id_from_path(path: Path) -> str | None:
    m = CHAPTER_FILE_RE.match(path.name)
    return f"ch{int(m.group(1))}" if m else None


def chapter_path(chapter_id: str) -> Path:
    n = int(chapter_id[2:])
    matches = sorted(
        p for p in BOOK_DIR.glob("*.md")
        if chapter_id_from_path(p) == f"ch{n}"
    )
    if not matches:
        raise FileNotFoundError(f"no chapter file for {chapter_id}")
    if len(matches) > 1:
        raise RuntimeError(f"ambiguous chapter file for {chapter_id}: {matches}")
    return matches[0]


def list_chapter_ids() -> list[str]:
    ids = sorted({
        cid for p in BOOK_DIR.glob("*.md")
        if (cid := chapter_id_from_path(p)) is not None
    }, key=lambda s: int(s[2:]))
    return ids


# ---------- anchors ----------

# Match markdown headings; level = number of leading '#'.
_HEADING_RE = re.compile(r"^(#{1,4})\s+(.*?)\s*$")
# Strip surrounding **bold**.
_BOLD_RE = re.compile(r"^\*\*(.+)\*\*$")
# Pull a numeric id like 12, 12.0, 12.0.2, 5.4a out of the front of a heading.
_NUMID_RE = re.compile(r"""
    ^\s*
    (?:§|\#)?\s*               # optional section sign
    (?:Chapter\s+)?            # optional 'Chapter '
    (\d+(?:\.\d+){0,3}[a-z]?)  # the id itself
    \s*[—\-:.]?\s*             # optional separator
    (.*)$
""", re.VERBOSE)


@dataclass
class Anchor:
    chapter_id: str
    anchor_id: str          # e.g. "12.0.2" or slug
    heading_text: str       # cleaned heading title (sans markup, sans numeric id)
    raw_heading: str        # raw line as it appears in the file (no trailing \n)
    level: int              # 1..4 = number of '#'s
    start_line: int         # 0-indexed line of the heading itself
    end_line: int           # 0-indexed exclusive; line index of next-or-same-level heading


def _slugify(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    text = re.sub(r"[\s_-]+", "-", text)
    return text or "section"


def parse_anchors(chapter_id: str, text: str) -> list[Anchor]:
    """Parse anchors out of a chapter. Levels 1..4 all become anchors;
    section scope (start/end_line) is computed by walking forward to the
    next heading whose level is <= this one."""
    lines = text.splitlines()
    raw: list[tuple[int, int, str, str]] = []
    for i, line in enumerate(lines):
        m = _HEADING_RE.match(line)
        if not m:
            continue
        level = len(m.group(1))
        title = m.group(2).strip()
        bold = _BOLD_RE.match(title)
        if bold:
            title = bold.group(1).strip()
        raw.append((i, level, title, line))

    anchors: list[Anchor] = []
    used_ids: set[str] = set()
    for idx, (line_no, level, title, raw_line) in enumerate(raw):
        # Determine end_line: next heading at level <= this one.
        end = len(lines)
        for j in range(idx + 1, len(raw)):
            if raw[j][1] <= level:
                end = raw[j][0]
                break

        # Extract numeric id if present.
        m = _NUMID_RE.match(title)
        if m and m.group(1):
            anchor_id = m.group(1)
            heading_text = m.group(2).strip() or title
        else:
            heading_text = title
            anchor_id = _slugify(title)

        # Disambiguate duplicates within this chapter.
        base = anchor_id
        n = 2
        while anchor_id in used_ids:
            anchor_id = f"{base}--{n}"
            n += 1
        used_ids.add(anchor_id)

        anchors.append(Anchor(
            chapter_id=chapter_id,
            anchor_id=anchor_id,
            heading_text=heading_text,
            raw_heading=raw_line,
            level=level,
            start_line=line_no,
            end_line=end,
        ))
    return anchors


def find_anchor(chapter_id: str, anchor_id: str) -> Anchor:
    text = chapter_path(chapter_id).read_text(encoding="utf-8")
    for a in parse_anchors(chapter_id, text):
        if a.anchor_id == anchor_id:
            return a
    raise KeyError(f"{chapter_id}/{anchor_id} not found")


def read_section(chapter_id: str, anchor_id: str) -> str:
    a = find_anchor(chapter_id, anchor_id)
    text = chapter_path(chapter_id).read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    return "".join(lines[a.start_line:a.end_line])


def replace_section(chapter_id: str, anchor_id: str, new_text: str) -> None:
    """Atomic section replacement. new_text either includes its heading
    (in which case it must start with the same heading marker line) or omits
    it (in which case we keep the original heading line and replace only
    the body). An empty string deletes the entire section, heading included."""
    path = chapter_path(chapter_id)
    a = find_anchor(chapter_id, anchor_id)
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)

    if new_text == "":
        replacement = []
    elif new_text.lstrip().startswith("#"):
        # full section incl. heading
        replacement = list(_ensure_trailing_newline(new_text).splitlines(keepends=True))
    else:
        replacement = [lines[a.start_line]] + list(
            _ensure_trailing_newline(new_text).splitlines(keepends=True)
        )

    new_lines = lines[: a.start_line] + replacement + lines[a.end_line:]
    new_content = "".join(new_lines)

    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(new_content, encoding="utf-8")
    tmp.replace(path)


def _ensure_trailing_newline(s: str) -> str:
    return s if s.endswith("\n") else s + "\n"


# ---------- machinery & footnotes ----------

# Default seed list of named machinery; refined via program.md when present.
DEFAULT_MACHINERY: tuple[str, ...] = (
    "Witness", "Canon", "Replicator", "Renormaliser",
    "Genesis Engine", "Stabilisation Engine", "Stratification Engine",
    "Genesis Assemblage", "Stratogonic Principle", "Synthesis Lemma",
    "Closure-Crisis Lemma", "Junction Thesis", "Landauer", "Landauer Floor",
    "Conservative Default", "Constructibility Test", "Regime-Variable Test",
    "Foreclosure Test", "Invoice-at-Installation Principle",
    "Dominant Causality Principle", "Maintenance Threshold",
    "Hamiltonian floor", "Symbolic Self", "Sixth Transduction",
    "Affective Witness", "Embodied Present", "Bioelectric Governor",
    "Offline Mind", "Symbolic Exit",
    "Canon Capture", "Parasitic Sclerosis", "Strategic Flooding",
    "Witness Degradation",
)
# Stratum N (N in 1..6) handled specially.
_STRATUM_RE = re.compile(r"\bStratum\s+\d+\b")


def load_machinery_terms() -> list[str]:
    """Pull machinery glossary from program.md if available; otherwise the
    default seed list above. Glossary is recognised as bullet items under a
    line matching '## Machinery glossary' (case-insensitive)."""
    if not PROGRAM_PATH.exists():
        return list(DEFAULT_MACHINERY)
    text = PROGRAM_PATH.read_text(encoding="utf-8")
    in_section = False
    out: list[str] = []
    for line in text.splitlines():
        if re.match(r"^##\s+machinery glossary\b", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section and re.match(r"^##\s", line):
            break
        if in_section:
            m = re.match(r"^\s*[-*]\s+\*\*(.+?)\*\*", line)
            if m:
                out.append(m.group(1).strip())
    return out or list(DEFAULT_MACHINERY)


def count_machinery(text: str, terms: list[str] | None = None) -> dict[str, int]:
    terms = terms or load_machinery_terms()
    counts: dict[str, int] = {}
    for t in terms:
        # word-bounded literal match (case-sensitive — these are proper-noun terms)
        pat = re.compile(rf"(?<!\w){re.escape(t)}(?!\w)")
        c = len(pat.findall(text))
        if c:
            counts[t] = c
    stratum_count = len(_STRATUM_RE.findall(text))
    if stratum_count:
        counts["Stratum N"] = stratum_count
    return counts


_FN_REF_RE = re.compile(r"\[\^([A-Za-z0-9_:.-]+)\]")
# A footnote definition: line beginning '[^id]:' (allow leading whitespace).
_FN_DEF_RE = re.compile(r"^\s*\[\^([A-Za-z0-9_:.-]+)\]:\s", re.MULTILINE)


def extract_footnotes(text: str) -> tuple[set[str], set[str]]:
    """Return (referenced_ids, defined_ids). A reference is any [^id]
    occurrence; a definition is a line of the form '[^id]: ...'."""
    defs = set(_FN_DEF_RE.findall(text))
    refs: set[str] = set()
    for m in _FN_REF_RE.finditer(text):
        # Skip the matches that are actually definitions (start of line + colon).
        start = m.start()
        line_start = text.rfind("\n", 0, start) + 1
        # check whether this match is followed by ':' before any newline -> definition
        after = text[m.end(): m.end() + 2]
        if after.startswith(":") and (start == line_start or text[line_start:start].strip() == ""):
            continue
        refs.add(m.group(1))
    return refs, defs


# ---------- metrics ----------

_SENT_RE = re.compile(r"[^.!?]+[.!?]+(?:[\"')\]]+)?")
_WORD_RE = re.compile(r"\b\w[\w'-]*\b")


def metrics(text: str) -> dict:
    words = _WORD_RE.findall(text)
    sentences = _SENT_RE.findall(text)
    word_count = len(words)
    sent_count = len(sentences) or 1
    em_dashes = text.count("—")
    paragraphs = [p for p in re.split(r"\n\s*\n", text) if p.strip()]
    return {
        "chars": len(text),
        "words": word_count,
        "sentences": sent_count,
        "avg_sentence_words": round(word_count / sent_count, 2),
        "em_dashes": em_dashes,
        "em_dash_per_kword": round(1000 * em_dashes / max(1, word_count), 2),
        "paragraphs": len(paragraphs),
    }


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


# ---------- baseline storage ----------


def baseline_path(chapter_id: str, anchor_id: str) -> Path:
    safe = anchor_id.replace("/", "_")
    return BASELINES_DIR / chapter_id / f"{safe}.md"


def chapter_baseline_path(chapter_id: str) -> Path:
    return BASELINES_DIR / chapter_id / "_chapter.md"


def has_baseline(chapter_id: str, anchor_id: str) -> bool:
    return baseline_path(chapter_id, anchor_id).exists()


def has_chapter_baseline(chapter_id: str) -> bool:
    return chapter_baseline_path(chapter_id).exists()


def read_baseline(chapter_id: str, anchor_id: str) -> str:
    return baseline_path(chapter_id, anchor_id).read_text(encoding="utf-8")


def read_chapter_baseline(chapter_id: str) -> str:
    return chapter_baseline_path(chapter_id).read_text(encoding="utf-8")


def write_baseline(chapter_id: str, anchor_id: str, content: str) -> None:
    p = baseline_path(chapter_id, anchor_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def write_chapter_baseline(chapter_id: str, content: str) -> None:
    p = chapter_baseline_path(chapter_id)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")


def load_baseline_meta() -> dict:
    if BASELINE_META_PATH.exists():
        return json.loads(BASELINE_META_PATH.read_text(encoding="utf-8"))
    return {}


def save_baseline_meta(meta: dict) -> None:
    BASELINE_META_PATH.write_text(
        json.dumps(meta, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


# ---------- helpers for revise.py ----------


@dataclass
class TripwireResult:
    name: str
    passed: bool
    detail: str = ""


def evaluate_tripwires(
    before: str,
    after: str,
    *,
    full_chapter_before: str,
    full_chapter_after: str,
    machinery_terms: list[str] | None = None,
    length_envelope: float = 0.25,
    deletion_authorized: bool = False,
    machinery_loss_authorized: bool = False,
) -> list[TripwireResult]:
    machinery_terms = machinery_terms or load_machinery_terms()
    out: list[TripwireResult] = []

    # 1. Machinery preservation.
    before_m = count_machinery(before, machinery_terms)
    after_m = count_machinery(after, machinery_terms)
    losses = {k: (before_m[k], after_m.get(k, 0)) for k in before_m
              if after_m.get(k, 0) < before_m[k]}
    if losses and not machinery_loss_authorized:
        out.append(TripwireResult(
            "machinery_preserved", False,
            "lost: " + ", ".join(f"{k} ({b}->{a})" for k, (b, a) in losses.items()),
        ))
    else:
        note = "no losses" if not losses else f"authorized losses: {losses}"
        out.append(TripwireResult("machinery_preserved", True, note))

    # 2. Footnote integrity (chapter-wide delta check). Pre-existing orphans
    # do not block the edit; new orphans introduced by the edit do.
    refs_b, defs_b = extract_footnotes(full_chapter_before)
    refs_a, defs_a = extract_footnotes(full_chapter_after)
    orphans_before = refs_b - defs_b
    orphans_after = refs_a - defs_a
    new_orphans = sorted(orphans_after - orphans_before)
    if new_orphans:
        out.append(TripwireResult(
            "footnotes_resolve", False,
            f"new undefined refs introduced: {new_orphans}",
        ))
    else:
        delta = len(orphans_after) - len(orphans_before)
        sign = "+" if delta >= 0 else ""
        out.append(TripwireResult(
            "footnotes_resolve", True,
            f"{len(refs_a)} refs / {len(defs_a)} defs "
            f"(orphans {len(orphans_before)} -> {len(orphans_after)}, {sign}{delta})",
        ))

    # 3. Length envelope (skipped if deletion authorized).
    before_w = metrics(before)["words"]
    after_w = metrics(after)["words"]
    if deletion_authorized:
        out.append(TripwireResult(
            "length_envelope", True,
            f"deletion authorized; {before_w}w -> {after_w}w",
        ))
    elif before_w == 0:
        out.append(TripwireResult(
            "length_envelope", True, f"baseline empty; {after_w}w added",
        ))
    else:
        delta = (after_w - before_w) / before_w
        if abs(delta) > length_envelope:
            out.append(TripwireResult(
                "length_envelope", False,
                f"{before_w}w -> {after_w}w ({delta:+.0%}, cap +-{length_envelope:.0%})",
            ))
        else:
            out.append(TripwireResult(
                "length_envelope", True,
                f"{before_w}w -> {after_w}w ({delta:+.0%})",
            ))

    return out


# ---------- inspection ----------


def list_anchors(chapter_id: str) -> list[Anchor]:
    text = chapter_path(chapter_id).read_text(encoding="utf-8")
    return parse_anchors(chapter_id, text)


def section_summary(chapter_id: str, anchor_id: str) -> dict:
    a = find_anchor(chapter_id, anchor_id)
    body = read_section(chapter_id, anchor_id)
    return {
        "chapter_id": chapter_id,
        "anchor": asdict(a),
        "metrics": metrics(body),
        "machinery": count_machinery(body),
        "content_hash": content_hash(body),
    }
