#!/usr/bin/env python3
"""
Step 5: Integrate blessed patches — create PR branch and open GitHub PR

Usage:
    python patch_integrate.py                      # integrate today's patches
    python patch_integrate.py --date 2026-03-25

Creates an integrate/<date>/<slug> branch from the working branch, cherry-picks
commits from the review branch, pushes to origin, and opens a GitHub PR via
the gh CLI.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

from config import Config
from utils import GitError, ensure_clean_worktree, ensure_local_branch, git_run, today_str


def _derive_integrate_branch(review_branch: str, cfg: Config) -> str:
    """Derive integrate/<date>/<slug> from review/<date>/<slug>."""
    parts = review_branch.split("/", 1)
    suffix = parts[1] if len(parts) == 2 else review_branch
    return f"{cfg.integrate_branch_prefix}/{suffix}"


_LGTM_CHECKED_RE = re.compile(r"-\s*\[x\].*\*\*LGTM\*\*", re.IGNORECASE)


def _print_report_hint(staging_dir: Path) -> None:
    """Print an informational hint about the review report and LGTM status.

    Mirrors bash/patch_integrate.sh's Approval Check section. This never
    blocks the flow — the actual approval gate is the yes/no prompt that
    follows in integrate_patches(). Any failure to read the report (bad
    encoding, permissions, or a race where the file disappears) degrades to
    the "not marked" warning instead of raising.
    """
    html_report = staging_dir / "REVIEW_REPORT.html"
    md_report = staging_dir / "REVIEW_REPORT.md"

    if html_report.exists():
        print(f"ℹ️  Review report (open this for review): {html_report}")

    if md_report.exists():
        print(f"ℹ️  Review report source (edit this to mark LGTM): {md_report}")
        try:
            text = md_report.read_text(errors="replace")
        except OSError:
            text = ""
        if _LGTM_CHECKED_RE.search(text):
            print("✅ Report shows LGTM approval (checkbox marked)")
        else:
            print("⚠️  Report exists but LGTM checkbox not marked")
    else:
        print(f"⚠️  No review report found at {md_report}")


def _create_github_pr(
    repo: Path, integrate_branch: str, base_branch: str, applied: list[dict]
) -> str | None:
    """Create a GitHub PR via gh CLI. Returns PR URL or None on failure."""
    title = f"Integrate: {applied[0]['subject'][:70]}" if applied else "Integrate patches"
    lines = ["Integrated patches via patch-pipeline:", ""]
    for c in applied:
        lines.append(f"- `{c['hash']}` {c['subject']}")
    body = "\n".join(lines)

    result = subprocess.run(
        ["gh", "pr", "create",
         "--base", base_branch,
         "--head", integrate_branch,
         "--title", title,
         "--body", body],
        capture_output=True,
        text=True,
        cwd=repo,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    return None


def integrate_patches(staging_dir: Path, cfg: Config) -> None:
    """Create integrate branch, cherry-pick review commits, push, open GitHub PR."""
    repo = cfg.repo_path
    base_branch = cfg.resolved_working_branch

    # Load apply data to find the review branch and commits
    apply_file = staging_dir / "apply_data.json"
    if not apply_file.exists():
        print(f"❌ No apply data found. Run patch_apply.py first.")
        sys.exit(1)

    with open(apply_file) as f:
        apply_data = json.load(f)

    review_branch = apply_data.get("branch")
    applied = apply_data.get("applied", [])

    if not review_branch or not applied:
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

    # Derive integrate branch name
    integrate_branch = _derive_integrate_branch(review_branch, cfg)

    # Sender blessing gate
    print(f"\n{'─' * 60}")
    print(f"Integration: {review_branch} → {integrate_branch} → PR → {base_branch}")
    print(f"Commits to cherry-pick: {len(applied)}")
    for c in applied:
        print(f"  {c['hash']}  {c['subject'][:60]}")
    print(f"{'─' * 60}\n")

    _print_report_hint(staging_dir)

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

    # Checkout base branch, then create integrate branch from it
    original_branch = git_run("rev-parse", "--abbrev-ref", "HEAD", cwd=repo).stdout.strip()
    print(f"\n🔄 Switching to {base_branch}...")
    try:
        ensure_local_branch(repo, base_branch)
        git_run("checkout", base_branch, cwd=repo)
    except GitError as e:
        print(f"❌ {e}")
        sys.exit(1)

    result = git_run("checkout", "-b", integrate_branch, cwd=repo, check=False)
    if result.returncode != 0:
        if "already exists" in result.stderr:
            print(f"❌ Branch '{integrate_branch}' already exists.")
            print(f"   Delete it first:  git branch -D {integrate_branch}")
        else:
            print(f"❌ Could not create branch: {result.stderr}")
        sys.exit(1)

    # Cherry-pick each commit from the review branch
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
                git_run("checkout", original_branch, cwd=repo, check=False)
                git_run("branch", "-D", integrate_branch, cwd=repo, check=False)
                print(f"Cherry-pick aborted and integrate branch cleaned up.")
            break

        print("✅")
        picked.append(commit)

    if len(picked) < len(applied):
        print(f"\n⚠️  Cherry-picked {len(picked)}/{len(applied)} commits (conflict encountered)")
        sys.exit(1)

    print(f"\n✅ All {len(picked)} commits cherry-picked to {integrate_branch}!")

    # Push integrate branch to origin
    print(f"\n📤 Pushing {integrate_branch} to origin...")
    push_result = git_run("push", "origin", integrate_branch, cwd=repo, check=False)
    if push_result.returncode != 0:
        print(f"⚠️  Push failed: {push_result.stderr.strip()}")
        print(f"   Push manually: git push origin {integrate_branch}")
    else:
        print("✅ Branch pushed.")

    # Open GitHub PR via gh CLI
    print(f"\n🔗 Creating GitHub PR ({integrate_branch} → {base_branch})...")
    pr_url = None
    if not shutil.which("gh"):
        print("⚠️  gh CLI not found. Create the PR manually:")
        print(f"   gh pr create --base {base_branch} --head {integrate_branch}")
    else:
        pr_url = _create_github_pr(repo, integrate_branch, base_branch, picked)
        if pr_url:
            print(f"✅ PR created: {pr_url}")
        else:
            print("⚠️  gh pr create failed. Create the PR manually:")
            print(f"   gh pr create --base {base_branch} --head {integrate_branch}")

    # Save integrate data
    integrate_data = {
        "review_branch": review_branch,
        "integrate_branch": integrate_branch,
        "base_branch": base_branch,
        "picked": picked,
        "pr_url": pr_url,
    }
    integrate_file = staging_dir / "integrate_data.json"
    with open(integrate_file, "w") as f:
        json.dump(integrate_data, f, indent=2)
    print(f"\n💾 Integrate data saved to {integrate_file}")

    print(f"\n{'─' * 60}")
    print(f"✅ Integration complete!")
    if pr_url:
        print(f"   PR: {pr_url}")
    print(f"   Branch: {integrate_branch}")
    print(f"   Target: {base_branch}")


def main():
    parser = argparse.ArgumentParser(description="Integrate blessed patches via PR branch")
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
