#!/usr/bin/env python3
"""
Step 5: Generate a markdown review report

Usage:
    python patch_report.py                         # report for today's patches
    python patch_report.py --date 2026-03-25

Collects data from all prior steps and generates REVIEW_REPORT.md.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from config import Config
from utils import format_table, today_str


def load_json(path: Path) -> dict | list | None:
    """Load a JSON file, return None if missing."""
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def generate_report(staging_dir: Path, cfg: Config) -> str:
    """Generate a markdown review report from all collected data."""
    date_str = staging_dir.name
    review = load_json(staging_dir / "review_data.json")
    apply = load_json(staging_dir / "apply_data.json")
    check = load_json(staging_dir / "check_data.json")
    tests = load_json(staging_dir / "test_data.json")

    lines = []
    lines.append(f"# Patch Review Report — {cfg.release} — {date_str}")
    lines.append(f"")
    lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    lines.append(f"")

    # Section 1: Patches Received
    lines.append(f"## Patches Received")
    lines.append(f"")
    if review and review.get("patches"):
        rows = []
        for i, p in enumerate(review["patches"], 1):
            rows.append([
                str(i),
                p.get("subject", "")[:55],
                p.get("author", "")[:30],
                str(p.get("files_changed", "?")),
                f"+{p.get('insertions', 0)}/-{p.get('deletions', 0)}",
            ])
        lines.append(format_table(["#", "Subject", "Author", "Files", "+/-"], rows))
    else:
        lines.append("_(No review data found — run patch_receive.py first)_")
    lines.append(f"")

    # Section 2: Review Notes & Warnings
    lines.append(f"## Review Notes")
    lines.append(f"")
    if review:
        warnings = review.get("all_warnings", [])
        if warnings:
            lines.append(f"### ⚠️ Warnings ({len(warnings)})")
            for w in warnings:
                lines.append(f"- {w}")
            lines.append(f"")

        notes = review.get("reviewer_notes", {})
        if notes:
            lines.append(f"### Reviewer Notes")
            for patch_name, note in notes.items():
                lines.append(f"- **{patch_name}**: {note}")
            lines.append(f"")
        elif not warnings:
            lines.append(f"No warnings. No reviewer notes.")
            lines.append(f"")
    else:
        lines.append("_(No review data)_")
        lines.append(f"")

    # Section 3: Apply Result
    lines.append(f"## Apply Result")
    lines.append(f"")
    if apply:
        lines.append(f"- **Branch**: `{apply.get('branch', '?')}`")
        lines.append(f"- **Base**: `{apply.get('base', '?')}`")
        applied = apply.get("applied", [])
        lines.append(f"- **Commits applied**: {len(applied)} / {apply.get('total', '?')}")

        if apply.get("failed"):
            fail = apply["failed"]
            lines.append(f"- **⚠️ Conflict**: Stopped at patch {fail.get('index', '?')} (`{fail.get('patch', '?')}`)")
            if fail.get("stripped_prefix"):
                lines.append(f"- **Root prefix mismatch**: Detected leading `{fail['stripped_prefix']}/` and stripped it for diagnostics")
            if fail.get("apply_check_error"):
                lines.append(f"- **Plain apply check**: `{fail['apply_check_error'][:240]}`")
        else:
            lines.append(f"- **Conflicts**: None ✅")

        if applied:
            lines.append(f"")
            lines.append(f"### Commits")
            for c in applied:
                lines.append(f"- `{c['hash']}` {c['subject'][:65]}")
    else:
        lines.append("_(No apply data — run patch_apply.py first)_")
    lines.append(f"")

    # Section 4: Functional Equivalence Check
    lines.append(f"## Functional Equivalence Check")
    lines.append(f"")
    if check:
        summary = check.get("summary", {})
        overall = check.get("overall", "UNKNOWN")
        icon = "✅" if overall == "PASS" else "⚠️"
        lines.append(f"**Overall: {icon} {overall}**  "
                     f"({summary.get('match',0)} MATCH, {summary.get('partial',0)} PARTIAL, "
                     f"{summary.get('mismatch',0)} MISMATCH, {summary.get('missing',0)} MISSING, "
                     f"{summary.get('extra',0)} EXTRA)")
        lines.append(f"")
        file_rows = []
        for fr in check.get("files", []):
            status_icon = {"MATCH":"✅","PARTIAL":"⚠️","MISMATCH":"❌","MISSING":"🔴","EXTRA":"➕"}.get(fr["status"],"❓")
            sim = f"{fr['similarity']:.0%}" if fr["status"] != "EXTRA" else "—"
            file_rows.append([fr["file"][-55:], f"{status_icon} {fr['status']}", sim])
        if file_rows:
            lines.append(format_table(["File", "Status", "Similarity"], file_rows))
        if overall != "PASS":
            lines.append(f"")
            lines.append(f"> ⚠️ MISMATCH or MISSING files indicate the sender's intended changes may not have "
                         f"landed correctly due to codebase differences. Confirm with sender before integrating.")
    else:
        lines.append("_(No check data — run patch_check.py first)_")
    lines.append(f"")

    # Section 5: Test Results
    lines.append(f"## Test Results")
    lines.append(f"")
    if tests:
        icon_map = {"PASS": "✅", "FAIL": "❌", "SKIPPED": "⏭️", "PENDING": "⏳", "TIMEOUT": "⏰", "ERROR": "💥"}
        rows = []
        for t in tests:
            icon = icon_map.get(t["result"], "❓")
            rows.append([t["test"], f"{icon} {t['result']}", t.get("notes", "")[:80]])
        lines.append(format_table(["Test", "Result", "Notes"], rows))
    else:
        lines.append("_(No test data — run patch_test.py first)_")
    lines.append(f"")

    # Section 6: Recommendation
    lines.append(f"## Reviewer Recommendation")
    lines.append(f"")
    lines.append(f"- [ ] **LGTM** — Ready for sender blessing. Recommend cherry-pick to working branch.")
    lines.append(f"- [ ] **Changes Requested** — See notes above. Sender should revise and resubmit.")
    lines.append(f"")
    lines.append(f"---")
    lines.append(f"_Reviewer signature: ___________________________  Date: _________ _")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Generate patch review report")
    parser.add_argument("--date", default=today_str(), help="Staging date (default: today)")
    parser.add_argument("--repo", help="Path to git repo (default: cwd)")
    parser.add_argument("--output", help="Output file path (default: staging dir)")
    args = parser.parse_args()

    cfg = Config.load(args.repo)
    staging = cfg.staging_path / args.date

    if not staging.is_dir():
        print(f"❌ No staged patches for {args.date}")
        sys.exit(1)

    report = generate_report(staging, cfg)

    if args.output:
        out_path = Path(args.output)
    else:
        out_path = staging / "REVIEW_REPORT.md"

    out_path.write_text(report)
    print(f"📄 Report saved to {out_path}")
    print(f"\n{report}")


if __name__ == "__main__":
    main()
