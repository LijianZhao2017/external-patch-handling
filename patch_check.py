#!/usr/bin/env python3
"""
Step 3: Functional equivalence check

Usage:
    python patch_check.py                          # check today's patches
    python patch_check.py --date 2026-03-25

Compares what the sender INTENDED (their patch) vs what ACTUALLY LANDED on the
receiver side (git diff main..review-branch). Because codebases diverge through
refactoring, the line numbers and context lines will differ — this tool looks
at the logical changes (added/removed content per file) and flags mismatches.

Output:
    - Per-file: MATCH / PARTIAL / MISMATCH / EXTRA
    - Side-by-side view of any divergent files
    - Saves check_data.json for the report
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from config import Config
from utils import detect_patch_root_prefix, format_table, git_run, list_patches, today_str


# ── Diff parsing ────────────────────────────────────────────────────────────

def _parse_diff_into_files(text: str) -> dict[str, dict]:
    """Parse a unified diff into per-file added/removed line sets.

    Returns {filename: {"added": [...], "removed": [...], "functions": [...]}}
    """
    files: dict[str, dict] = {}
    current: dict | None = None

    for line in text.split("\n"):
        if line.startswith("diff --git "):
            m = re.search(r"diff --git a/(.+?) b/", line)
            if m:
                fname = m.group(1)
                current = {"added": [], "removed": [], "functions": []}
                files[fname] = current
        elif current is None:
            continue
        elif line.startswith("@@"):
            # @@ -a,b +c,d @@ optional_function_name
            m = re.search(r"@@[^@]*@@\s*(.*)", line)
            fn = m.group(1).strip() if m else ""
            if fn and fn not in current["functions"]:
                current["functions"].append(fn)
        elif line.startswith("+") and not line.startswith("+++"):
            current["added"].append(line[1:].strip())
        elif line.startswith("-") and not line.startswith("---"):
            current["removed"].append(line[1:].strip())

    return files


def _token_similarity(a: list[str], b: list[str]) -> float:
    """Jaccard similarity between two lists of lines (ignores empty lines)."""
    sa = set(s for s in a if s)
    sb = set(s for s in b if s)
    if not sa and not sb:
        return 1.0
    union = sa | sb
    return len(sa & sb) / len(union)


def _classify(score: float) -> str:
    if score >= 0.75:
        return "MATCH"
    if score >= 0.40:
        return "PARTIAL"
    return "MISMATCH"


# ── Side-by-side display ────────────────────────────────────────────────────

def _side_by_side(fname: str, sender: dict, receiver: dict) -> str:
    """Render a side-by-side diff of added lines for a single file."""
    s_add = sender["added"]
    r_add = receiver["added"]
    s_rem = sender["removed"]
    r_rem = receiver["removed"]

    lines = [f"\n  File: {fname}"]
    lines.append(f"  {'SENDER added':<45}  {'RECEIVER added'}")
    lines.append(f"  {'─'*45}  {'─'*45}")

    max_rows = max(len(s_add), len(r_add), 1)
    for i in range(min(max_rows, 20)):  # cap at 20 lines per file
        sl = s_add[i][:44] if i < len(s_add) else ""
        rl = r_add[i][:44] if i < len(r_add) else ""
        marker = "  " if sl == rl else "≠ "
        lines.append(f"  {marker}{sl:<45}  {rl}")
    if max_rows > 20:
        lines.append(f"  ... ({max_rows - 20} more lines not shown)")

    if s_rem or r_rem:
        lines.append(f"  {'SENDER removed':<45}  {'RECEIVER removed'}")
        lines.append(f"  {'─'*45}  {'─'*45}")
        max_rem = max(len(s_rem), len(r_rem), 1)
        for i in range(min(max_rem, 10)):
            sl = s_rem[i][:44] if i < len(s_rem) else ""
            rl = r_rem[i][:44] if i < len(r_rem) else ""
            marker = "  " if sl == rl else "≠ "
            lines.append(f"  {marker}{sl:<45}  {rl}")

    return "\n".join(lines)


# ── Main check ──────────────────────────────────────────────────────────────

def check_equivalence(staging_dir: Path, cfg: Config) -> dict:
    """Compare sender patches vs receiver applied diff. Returns check_data."""
    repo = cfg.repo_path

    # Load apply data for branch name
    apply_file = staging_dir / "apply_data.json"
    if not apply_file.exists():
        print("❌ No apply data. Run patch_apply.py first.")
        sys.exit(1)
    apply_data = json.loads(apply_file.read_text())
    review_branch = apply_data["branch"]
    base_branch = apply_data["base"]

    # Build combined sender diff from staged patches
    sender_patches = list_patches(staging_dir)
    if not sender_patches:
        print(f"❌ No staged patches in {staging_dir}")
        sys.exit(1)
    sender_text = "\n".join(p.read_text(errors="replace") for p in sender_patches)
    sender_files = _parse_diff_into_files(sender_text)

    # Strip redundant repo-root prefix from sender paths (e.g. "Intel/Pkg/foo.c" → "Pkg/foo.c")
    prefix = detect_patch_root_prefix(list(sender_files.keys()), repo)
    if prefix:
        sender_files = {k[len(prefix) + 1:]: v for k, v in sender_files.items()}

    # Get the base from the parent of the first applied commit — more reliable
    # than branch name, handles master/main differences and detached HEAD cases
    applied = apply_data.get("applied", [])
    if not applied:
        print("❌ No applied commits in apply_data. Nothing to check.")
        sys.exit(1)

    first_hash = applied[0]["hash"]
    parent_result = git_run("rev-parse", f"{first_hash}^", cwd=repo, check=False)
    if parent_result.returncode != 0:
        print(f"❌ Cannot find parent of first applied commit {first_hash}")
        sys.exit(1)
    base_ref = parent_result.stdout.strip()

    # Get receiver's actual applied diff
    result = git_run("diff", base_ref, review_branch, "--", cwd=repo)
    receiver_files = _parse_diff_into_files(result.stdout)

    print(f"📊 Functional Equivalence Check")
    print(f"   Sender patches : {len(sender_files)} file(s) changed")
    print(f"   Receiver diff  : {review_branch} vs {base_branch} — {len(receiver_files)} file(s)")
    print()

    file_results = []
    details_lines = []

    # Check every file the sender touched
    for fname in sorted(sender_files):
        s = sender_files[fname]
        if fname in receiver_files:
            r = receiver_files[fname]
            add_score = _token_similarity(s["added"], r["added"])
            rem_score = _token_similarity(s["removed"], r["removed"])
            score = (add_score + rem_score) / 2
            status = _classify(score)
        else:
            score = 0.0
            status = "MISSING"
            r = {"added": [], "removed": [], "functions": []}

        file_results.append({
            "file": fname,
            "status": status,
            "similarity": round(score, 2),
            "sender_added": len(s["added"]),
            "receiver_added": len(r["added"]),
            "functions": s["functions"],
        })

        if status in ("PARTIAL", "MISMATCH", "MISSING"):
            details_lines.append(_side_by_side(fname, s, r))

    # Files only on receiver side (extra changes not in sender patch)
    extra_files = []
    for fname in sorted(receiver_files):
        if fname not in sender_files:
            extra_files.append(fname)
            file_results.append({
                "file": fname,
                "status": "EXTRA",
                "similarity": 0.0,
                "sender_added": 0,
                "receiver_added": len(receiver_files[fname]["added"]),
                "functions": receiver_files[fname]["functions"],
            })

    # Print table
    rows = []
    for fr in file_results:
        icon = {"MATCH": "✅", "PARTIAL": "⚠️ ", "MISMATCH": "❌", "MISSING": "🔴", "EXTRA": "➕"}.get(fr["status"], "❓")
        rows.append([
            fr["file"][-50:],
            f"{icon} {fr['status']}",
            f"{fr['similarity']:.0%}" if fr["status"] != "EXTRA" else "—",
            str(fr["sender_added"]),
            str(fr["receiver_added"]),
        ])
    print(format_table(["File", "Status", "Similarity", "Sender+", "Receiver+"], rows))

    # Summary counts
    statuses = [fr["status"] for fr in file_results]
    n_match = statuses.count("MATCH")
    n_partial = statuses.count("PARTIAL")
    n_mismatch = statuses.count("MISMATCH")
    n_missing = statuses.count("MISSING")
    n_extra = statuses.count("EXTRA")

    print(f"\nSummary: {n_match} MATCH  {n_partial} PARTIAL  {n_mismatch} MISMATCH  {n_missing} MISSING  {n_extra} EXTRA")

    if details_lines:
        print(f"\n{'─'*60}")
        print("⚠️  Files needing attention (side-by-side):")
        for d in details_lines:
            print(d)

    if extra_files:
        print(f"\n➕ Extra files changed on receiver side (not in sender patch):")
        for f in extra_files:
            print(f"   {f}")
        print("   → Verify these are adaptation changes (context adjustments), not unintended modifications.")

    overall = "PASS" if n_mismatch == 0 and n_missing == 0 else "NEEDS REVIEW"
    print(f"\n{'─'*60}")
    print(f"Overall: {'✅ ' if overall == 'PASS' else '⚠️  '}{overall}")
    if overall == "NEEDS REVIEW":
        print("  MISMATCH/MISSING files mean the sender's intent may not have landed correctly.")
        print("  Review the side-by-side above and confirm with the sender before proceeding.")

    check_data = {
        "review_branch": review_branch,
        "base_branch": base_branch,
        "files": file_results,
        "overall": overall,
        "summary": {"match": n_match, "partial": n_partial, "mismatch": n_mismatch,
                    "missing": n_missing, "extra": n_extra},
    }
    (staging_dir / "check_data.json").write_text(json.dumps(check_data, indent=2))
    print(f"\n💾 Check data saved to {staging_dir / 'check_data.json'}")

    return check_data


def main():
    parser = argparse.ArgumentParser(description="Check functional equivalence of applied patches")
    parser.add_argument("--date", default=today_str(), help="Staging date (default: today)")
    parser.add_argument("--repo", help="Path to git repo (default: cwd)")
    args = parser.parse_args()

    cfg = Config.load(args.repo)
    staging = cfg.staging_path / args.date

    if not staging.is_dir():
        print(f"❌ No staged patches for {args.date}")
        sys.exit(1)

    check_equivalence(staging, cfg)


if __name__ == "__main__":
    main()
