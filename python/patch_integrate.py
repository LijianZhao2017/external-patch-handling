#!/usr/bin/env python3
"""
Step 5b: Integrate blessed patches into the working branch

Usage:
    python patch_integrate.py                      # integrate today's patches
    python patch_integrate.py --date 2026-03-25

Cherry-picks commits from the review branch to the working branch.
Requires sender blessing (interactive confirmation).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from config import Config
from utils import GitError, ensure_clean_worktree, ensure_local_branch, git_run, today_str


def integrate_patches(staging_dir: Path, cfg: Config) -> None:
    """Cherry-pick review branch commits to working branch."""
    repo = cfg.repo_path
    base_branch = cfg.resolved_working_branch

    # Load apply data to find the review branch
    apply_file = staging_dir / "apply_data.json"
    if not apply_file.exists():
        print(f"❌ No apply data found. Run patch_apply.py first.")
        sys.exit(1)

    with open(apply_file) as f:
        apply_data = json.load(f)

    branch = apply_data.get("branch")
    applied = apply_data.get("applied", [])

    if not branch or not applied:
        print(f"❌ No commits to integrate. Check apply_data.json.")
        sys.exit(1)

    if apply_data.get("failed"):
        print(f"⚠️  The apply had a conflict. Only {len(applied)} of {apply_data['total']} patches were applied.")
        try:
            proceed = input("   Continue with partial integration? (y/N): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            proceed = "n"
        if proceed != "y":
            print("Aborted.")
            sys.exit(0)

    # Sender blessing gate
    print(f"\n{'─' * 60}")
    print(f"Integration: {branch} → {base_branch}")
    print(f"Commits to cherry-pick: {len(applied)}")
    for c in applied:
        print(f"  {c['hash']}  {c['subject'][:60]}")
    print(f"{'─' * 60}\n")

    try:
        blessed = input("Has the sender blessed these changes? (yes/no): ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        blessed = "no"

    if blessed not in ("yes", "y"):
        print("❌ Sender blessing required before integration. Aborted.")
        sys.exit(0)

    # Ensure clean worktree
    try:
        ensure_clean_worktree(repo, ignored_paths=[cfg.staging_dir])
    except GitError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Switch to working branch
    print(f"\n🔄 Switching to {base_branch}...")
    try:
        ensure_local_branch(repo, base_branch)
        git_run("checkout", base_branch, cwd=repo)
    except GitError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Cherry-pick each commit
    print(f"🍒 Cherry-picking {len(applied)} commit(s)...\n")
    picked = []

    for i, commit in enumerate(applied, 1):
        hash_val = commit["hash"]
        print(f"  [{i}/{len(applied)}] {hash_val} {commit['subject'][:50]}...", end=" ")

        result = git_run("cherry-pick", hash_val, cwd=repo, check=False)

        if result.returncode != 0:
            print("❌ CONFLICT")
            print(f"\n{'─' * 60}")
            print(f"Conflict during cherry-pick of {hash_val}")
            print(f"Git output:\n{result.stderr}")
            print(f"\nTo resolve:")
            print(f"  1. Fix conflicts")
            print(f"  2. git add <files>")
            print(f"  3. git cherry-pick --continue")
            try:
                abort = input("\nAbort cherry-pick now and restore branch? (Y/n): ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                abort = "y"
            if abort != "n":
                git_run("cherry-pick", "--abort", cwd=repo, check=False)
                print("Cherry-pick aborted. Working branch restored.")
            break

        print("✅")
        picked.append(commit)

    print(f"\n{'─' * 60}")
    if len(picked) == len(applied):
        print(f"✅ All {len(picked)} commits cherry-picked to {base_branch}!")
        print(f"\nNext steps:")
        print(f"  1. Review: git log --oneline -{len(picked)}")
        print(f"  2. Push:   git push origin {base_branch}")
        print(f"  3. Build from {base_branch}")
    else:
        print(f"⚠️  Cherry-picked {len(picked)}/{len(applied)} commits (conflict encountered)")


def main():
    parser = argparse.ArgumentParser(description="Integrate blessed patches to working branch")
    parser.add_argument("--date", default=today_str(), help="Staging date (default: today)")
    parser.add_argument("--repo", help="Path to git repo (default: cwd)")
    args = parser.parse_args()

    cfg = Config.load(args.repo)
    staging = cfg.staging_path / args.date

    if not staging.is_dir():
        print(f"❌ No staged patches for {args.date}")
        sys.exit(1)

    integrate_patches(staging, cfg)


if __name__ == "__main__":
    main()
