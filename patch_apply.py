#!/usr/bin/env python3
"""
Step 2: Apply patches to a dedicated review branch

Usage:
    python patch_apply.py                          # apply today's staged patches
    python patch_apply.py --date 2026-03-25        # apply a specific date's patches

Creates a review branch and applies all patches with git am --3way.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import Config
from utils import (
    GitError,
    ensure_clean_worktree,
    git_run,
    list_patches,
    parse_patch_header,
    slugify,
    today_str,
)


def apply_patches(staging_dir: Path, cfg: Config) -> dict:
    """Apply all patches from staging to a new review branch."""
    repo = cfg.repo_path
    patches = list_patches(staging_dir)
    if not patches:
        print(f"❌ No patches in {staging_dir}")
        sys.exit(1)

    # Ensure clean worktree
    try:
        ensure_clean_worktree(repo)
    except GitError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Determine branch name from first patch subject
    first_info = parse_patch_header(patches[0])
    slug = slugify(first_info["subject"])
    date_str = staging_dir.name  # e.g. "2026-03-26"
    branch_name = f"{cfg.review_branch_prefix}/{date_str}/{slug}"

    print(f"📦 Applying {len(patches)} patch(es) to branch: {branch_name}")
    print(f"   Base: {cfg.working_branch}\n")

    # Checkout working branch and create review branch
    try:
        git_run("checkout", cfg.working_branch, cwd=repo)
    except GitError:
        print(f"⚠️  Could not checkout {cfg.working_branch}, using current HEAD")

    result = git_run("checkout", "-b", branch_name, cwd=repo, check=False)
    if result.returncode != 0:
        if "already exists" in result.stderr:
            print(f"❌ Branch '{branch_name}' already exists.")
            print(f"   Delete it first:  git branch -D {branch_name}")
            print(f"   Or use --force to overwrite (re-runs git am from scratch).")
        else:
            print(f"❌ Could not create branch: {result.stderr}")
        sys.exit(1)

    # Apply each patch
    applied = []
    failed = None

    for i, patch_path in enumerate(patches, 1):
        info = parse_patch_header(patch_path)
        print(f"  [{i}/{len(patches)}] Applying: {info['subject'][:60]}...", end=" ")

        result = git_run(
            "am", "--3way", str(patch_path),
            cwd=repo,
            check=False,
        )

        if result.returncode != 0:
            print("❌ CONFLICT")
            print(f"\n{'─' * 60}")
            print(f"Conflict while applying patch {i}: {patch_path.name}")
            print(f"Git output:\n{result.stderr}")
            print(f"\nTo resolve manually:")
            print(f"  1. Fix conflicts in the listed files")
            print(f"  2. git add <resolved-files>")
            print(f"  3. git am --continue")
            print(f"  Or to abort: git am --abort && git checkout {cfg.working_branch} && git branch -D {branch_name}")
            failed = {"patch": patch_path.name, "index": i, "error": result.stderr}
            break

        print("✅")

        # Get the commit hash just created
        log = git_run("log", "-1", "--format=%H %s", cwd=repo)
        parts = log.stdout.strip().split(" ", 1)
        applied.append({"hash": parts[0][:12], "subject": parts[1] if len(parts) > 1 else ""})

    # Result summary
    apply_data = {
        "branch": branch_name,
        "base": cfg.working_branch,
        "applied": applied,
        "failed": failed,
        "total": len(patches),
    }

    print(f"\n{'─' * 60}")
    if failed:
        print(f"⚠️  Applied {len(applied)}/{len(patches)} patches (stopped at conflict)")
    else:
        print(f"✅ All {len(patches)} patches applied successfully!")
        print(f"\nApplied commits:")
        for c in applied:
            print(f"  {c['hash']}  {c['subject'][:65]}")

    print(f"\nReview branch: {branch_name}")

    # Save apply data for report
    apply_file = staging_dir / "apply_data.json"
    with open(apply_file, "w") as f:
        json.dump(apply_data, f, indent=2)
    print(f"💾 Apply data saved to {apply_file}")

    return apply_data


def main():
    parser = argparse.ArgumentParser(description="Apply staged patches to review branch")
    parser.add_argument("--date", default=today_str(), help="Staging date (default: today)")
    parser.add_argument("--repo", help="Path to git repo (default: cwd)")
    args = parser.parse_args()

    cfg = Config.load(args.repo)
    staging = cfg.staging_path / args.date

    if not staging.is_dir():
        print(f"❌ No staged patches for {args.date}")
        sys.exit(1)

    apply_patches(staging, cfg)


if __name__ == "__main__":
    main()
