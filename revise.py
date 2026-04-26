#!/usr/bin/env python3
"""
revise.py — one iteration of the AutoResearch-style book loop.

Subcommands (Phase 1):
    init                            snapshot every section into .baselines/
    status                          summarise baselines + recent journal entries
    list-chapters                   print chapter ids
    list-anchors <ch>               print anchors of a chapter (id, level, heading)
    list-pain                       print pain queue from program.md
    inspect <ch> <anchor>           print section text and metrics
    metrics <ch> <anchor>           print metrics + machinery counts
    diff <ch> <anchor>              show baseline vs current section
    validate <ch> <anchor> [flags]  run tripwires (current vs baseline)
    accept <ch> <anchor> --reason   promote current to baseline; log + changelog
    revert <ch> <anchor>            restore section text from baseline

Phase-1 acceptance is tripwires-only (machinery preserved, footnotes resolve,
length envelope). The LLM-as-judge composite score arrives in Phase 2.

The contract:
    * the agent only edits files inside book/
    * the agent never edits prepare.py, revise.py, baseline.json, journal.jsonl,
      .baselines/, or CHANGELOG.md
    * program.md is human-curated; the agent reads it but does not write it
"""

from __future__ import annotations

import argparse
import datetime as dt
import difflib
import json
import re
import sys
from dataclasses import asdict
from pathlib import Path

import prepare


# ---------- pain queue ----------


def parse_pain_queue() -> list[dict]:
    """Pain items live under '## Pain queue' in program.md as fenced YAML-ish
    bullet blocks. Each item begins with '- id: <slug>' and may declare:
        chapter: ch12
        anchor: notes-on-this-refinement      (id or slug)
        operation: delete | revise | extend
        deletion_authorized: true|false
        machinery_loss_authorized: true|false
        reason: short rationale
        note: free text (optional)
    """
    if not prepare.PROGRAM_PATH.exists():
        return []
    text = prepare.PROGRAM_PATH.read_text(encoding="utf-8")
    in_section = False
    block: list[str] = []
    items: list[dict] = []

    def flush(b: list[str]) -> None:
        if not b:
            return
        d: dict = {}
        for raw in b:
            m = re.match(r"^\s*-\s+(\w+):\s*(.+?)\s*$", raw)
            if m:
                key, val = m.group(1), m.group(2)
                if val.lower() in ("true", "false"):
                    d[key] = val.lower() == "true"
                else:
                    d[key] = val.strip().strip('"').strip("'")
        if d:
            items.append(d)

    for line in text.splitlines():
        if re.match(r"^##\s+pain queue\b", line, re.IGNORECASE):
            in_section = True
            continue
        if in_section and re.match(r"^##\s", line):
            flush(block)
            block = []
            break
        if not in_section:
            continue
        # blank line ends an item block
        if not line.strip():
            flush(block)
            block = []
            continue
        block.append(line)
    flush(block)
    return items


def find_pain_item(chapter_id: str, anchor_id: str) -> dict | None:
    for it in parse_pain_queue():
        if it.get("chapter") == chapter_id and it.get("anchor") == anchor_id:
            return it
    return None


# ---------- journal ----------


def journal_append(event: dict) -> None:
    event = {"ts": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z", **event}
    with prepare.JOURNAL_PATH.open("a", encoding="utf-8") as f:
        f.write(json.dumps(event, sort_keys=True) + "\n")


def changelog_append(line: str) -> None:
    if not prepare.CHANGELOG_PATH.exists():
        prepare.CHANGELOG_PATH.write_text(
            "# Changelog\n\nAccepted edits, newest first.\n\n", encoding="utf-8"
        )
    existing = prepare.CHANGELOG_PATH.read_text(encoding="utf-8")
    head, _, body = existing.partition("\n\n")
    # insert under the second blank line
    parts = existing.split("\n\n", 2)
    if len(parts) >= 3:
        head_two = "\n\n".join(parts[:2]) + "\n\n"
        rest = parts[2]
    else:
        head_two = existing.rstrip() + "\n\n"
        rest = ""
    prepare.CHANGELOG_PATH.write_text(head_two + line + "\n" + rest, encoding="utf-8")


# ---------- subcommands ----------


def cmd_init(args: argparse.Namespace) -> int:
    chapters = prepare.list_chapter_ids()
    meta = prepare.load_baseline_meta()
    new_count = 0
    for ch in chapters:
        # Snapshot the full chapter so chapter-level tripwires can do delta
        # comparisons even after deletions.
        full = prepare.chapter_path(ch).read_text(encoding="utf-8")
        if (not prepare.has_chapter_baseline(ch)) or args.force:
            prepare.write_chapter_baseline(ch, full)
        anchors = prepare.list_anchors(ch)
        for a in anchors:
            if prepare.has_baseline(ch, a.anchor_id) and not args.force:
                continue
            content = prepare.read_section(ch, a.anchor_id)
            prepare.write_baseline(ch, a.anchor_id, content)
            meta.setdefault(ch, {})[a.anchor_id] = {
                "accepted_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
                "reason": "initial baseline",
                "content_hash": prepare.content_hash(content),
                "metrics": prepare.metrics(content),
                "machinery": prepare.count_machinery(content),
                "heading": a.raw_heading.strip(),
            }
            new_count += 1
    prepare.save_baseline_meta(meta)
    journal_append({"event": "init", "baselined": new_count, "chapters": chapters})
    print(f"baselined {new_count} sections across {len(chapters)} chapters")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    meta = prepare.load_baseline_meta()
    print(f"chapters baselined: {len(meta)}")
    total = sum(len(v) for v in meta.values())
    print(f"sections baselined: {total}")
    if prepare.JOURNAL_PATH.exists():
        lines = prepare.JOURNAL_PATH.read_text(encoding="utf-8").splitlines()
        print(f"journal entries:    {len(lines)}")
        if lines:
            print("\nlast 5 events:")
            for ln in lines[-5:]:
                e = json.loads(ln)
                ev = e.get("event", "?")
                ch = e.get("chapter", "")
                an = e.get("anchor", "")
                ts = e.get("ts", "")
                print(f"  {ts}  {ev:8s}  {ch}/{an}")
    return 0


def cmd_list_chapters(args: argparse.Namespace) -> int:
    for ch in prepare.list_chapter_ids():
        path = prepare.chapter_path(ch)
        anchors = prepare.list_anchors(ch)
        words = prepare.metrics(path.read_text(encoding="utf-8"))["words"]
        print(f"  {ch:6s}  {len(anchors):3d} anchors  {words:>6,d} words  {path.name}")
    return 0


def cmd_list_anchors(args: argparse.Namespace) -> int:
    for a in prepare.list_anchors(args.chapter):
        marker = " " * (a.level - 1) * 2
        print(f"  L{a.level} {a.anchor_id:20s} {marker}{a.heading_text}")
    return 0


def cmd_list_pain(args: argparse.Namespace) -> int:
    items = parse_pain_queue()
    if not items:
        print("(pain queue empty)")
        return 0
    for it in items:
        flags = []
        if it.get("deletion_authorized"):
            flags.append("DEL")
        if it.get("machinery_loss_authorized"):
            flags.append("MACH")
        flag_str = (" [" + ",".join(flags) + "]") if flags else ""
        print(
            f"  {it.get('id','?'):28s} "
            f"{it.get('chapter','?')}/{it.get('anchor','?'):28s} "
            f"{it.get('operation','?'):8s}{flag_str}  "
            f"{it.get('reason','')}"
        )
    return 0


def cmd_inspect(args: argparse.Namespace) -> int:
    summary = prepare.section_summary(args.chapter, args.anchor)
    print(json.dumps(summary, indent=2, sort_keys=True))
    print("---- content ----")
    print(prepare.read_section(args.chapter, args.anchor), end="")
    return 0


def cmd_metrics(args: argparse.Namespace) -> int:
    body = prepare.read_section(args.chapter, args.anchor)
    print(json.dumps({
        "metrics": prepare.metrics(body),
        "machinery": prepare.count_machinery(body),
        "content_hash": prepare.content_hash(body),
    }, indent=2, sort_keys=True))
    return 0


def cmd_diff(args: argparse.Namespace) -> int:
    if not prepare.has_baseline(args.chapter, args.anchor):
        print(f"no baseline for {args.chapter}/{args.anchor}", file=sys.stderr)
        return 2
    before = prepare.read_baseline(args.chapter, args.anchor)
    after = prepare.read_section(args.chapter, args.anchor)
    diff = difflib.unified_diff(
        before.splitlines(keepends=True),
        after.splitlines(keepends=True),
        fromfile=f"baseline:{args.chapter}/{args.anchor}",
        tofile=f"current:{args.chapter}/{args.anchor}",
        n=3,
    )
    sys.stdout.writelines(diff)
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    if not prepare.has_baseline(args.chapter, args.anchor):
        print(f"no baseline for {args.chapter}/{args.anchor}", file=sys.stderr)
        return 2
    before = prepare.read_baseline(args.chapter, args.anchor)
    full_after = prepare.chapter_path(args.chapter).read_text(encoding="utf-8")
    # If the section heading was removed (deletion), read_section will raise
    # KeyError. Treat that as after = "".
    try:
        after = prepare.read_section(args.chapter, args.anchor)
    except KeyError:
        after = ""
    full_before = (
        prepare.read_chapter_baseline(args.chapter)
        if prepare.has_chapter_baseline(args.chapter)
        else full_after
    )

    pain = find_pain_item(args.chapter, args.anchor)
    deletion = bool(args.deletion_authorized or (pain and pain.get("deletion_authorized")))
    mach_ok = bool(args.machinery_loss_authorized or (pain and pain.get("machinery_loss_authorized")))

    results = prepare.evaluate_tripwires(
        before, after,
        full_chapter_before=full_before,
        full_chapter_after=full_after,
        deletion_authorized=deletion,
        machinery_loss_authorized=mach_ok,
    )

    all_pass = all(r.passed for r in results)
    print(f"{args.chapter}/{args.anchor}: {'PASS' if all_pass else 'FAIL'}")
    for r in results:
        mark = "[ok]  " if r.passed else "[FAIL]"
        print(f"  {mark} {r.name:22s} {r.detail}")

    journal_append({
        "event": "validate",
        "chapter": args.chapter,
        "anchor": args.anchor,
        "passed": all_pass,
        "results": [asdict(r) for r in results],
        "before_hash": prepare.content_hash(before),
        "after_hash": prepare.content_hash(after),
    })
    return 0 if all_pass else 1


def cmd_accept(args: argparse.Namespace) -> int:
    rc = cmd_validate(args)
    if rc != 0:
        print("validate failed; not accepting", file=sys.stderr)
        return rc
    try:
        after = prepare.read_section(args.chapter, args.anchor)
    except KeyError:
        after = ""
    prepare.write_baseline(args.chapter, args.anchor, after)
    # Refresh the full-chapter baseline so future tripwires compare against
    # the post-accept chapter state.
    prepare.write_chapter_baseline(
        args.chapter,
        prepare.chapter_path(args.chapter).read_text(encoding="utf-8"),
    )
    meta = prepare.load_baseline_meta()
    meta.setdefault(args.chapter, {})[args.anchor] = {
        "accepted_at": dt.datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "reason": args.reason,
        "content_hash": prepare.content_hash(after),
        "metrics": prepare.metrics(after),
        "machinery": prepare.count_machinery(after),
    }
    prepare.save_baseline_meta(meta)
    journal_append({
        "event": "accept",
        "chapter": args.chapter,
        "anchor": args.anchor,
        "reason": args.reason,
        "after_hash": prepare.content_hash(after),
    })
    changelog_append(
        f"- **{args.chapter}/{args.anchor}** — {args.reason} "
        f"({dt.datetime.utcnow().date().isoformat()})"
    )
    print(f"accepted {args.chapter}/{args.anchor}")
    return 0


def cmd_revert(args: argparse.Namespace) -> int:
    if not prepare.has_baseline(args.chapter, args.anchor):
        print(f"no baseline for {args.chapter}/{args.anchor}", file=sys.stderr)
        return 2
    if not prepare.has_chapter_baseline(args.chapter):
        print(f"no chapter baseline for {args.chapter}", file=sys.stderr)
        return 2
    # Revert by restoring the entire chapter from its baseline snapshot. This
    # works whether the edit was a modification or a section deletion.
    chapter_baseline = prepare.read_chapter_baseline(args.chapter)
    prepare.chapter_path(args.chapter).write_text(chapter_baseline, encoding="utf-8")
    journal_append({
        "event": "revert",
        "chapter": args.chapter,
        "anchor": args.anchor,
    })
    print(f"reverted {args.chapter} to chapter baseline (anchor {args.anchor} restored)")
    return 0


# ---------- main ----------


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="revise")
    sub = p.add_subparsers(dest="cmd", required=True)

    p_init = sub.add_parser("init", help="snapshot every section into .baselines/")
    p_init.add_argument("--force", action="store_true",
                        help="overwrite existing baselines")
    p_init.set_defaults(func=cmd_init)

    sub.add_parser("status", help="summary").set_defaults(func=cmd_status)
    sub.add_parser("list-chapters", help="list chapter ids").set_defaults(func=cmd_list_chapters)

    p_la = sub.add_parser("list-anchors", help="list anchors of a chapter")
    p_la.add_argument("chapter")
    p_la.set_defaults(func=cmd_list_anchors)

    sub.add_parser("list-pain", help="show pain queue").set_defaults(func=cmd_list_pain)

    for name, func in (("inspect", cmd_inspect), ("metrics", cmd_metrics),
                       ("diff", cmd_diff), ("revert", cmd_revert)):
        sp = sub.add_parser(name)
        sp.add_argument("chapter")
        sp.add_argument("anchor")
        sp.set_defaults(func=func)

    p_val = sub.add_parser("validate", help="run tripwires")
    p_val.add_argument("chapter")
    p_val.add_argument("anchor")
    p_val.add_argument("--deletion-authorized", action="store_true",
                       help="explicit override (also readable from program.md)")
    p_val.add_argument("--machinery-loss-authorized", action="store_true")
    p_val.set_defaults(func=cmd_validate)

    p_acc = sub.add_parser("accept", help="promote current to baseline")
    p_acc.add_argument("chapter")
    p_acc.add_argument("anchor")
    p_acc.add_argument("--reason", required=True)
    p_acc.add_argument("--deletion-authorized", action="store_true")
    p_acc.add_argument("--machinery-loss-authorized", action="store_true")
    p_acc.set_defaults(func=cmd_accept)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except BrokenPipeError:
        sys.exit(0)
