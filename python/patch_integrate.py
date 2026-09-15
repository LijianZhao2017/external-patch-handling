#!/usr/bin/env python3
"""
Step 5: Integrate blessed patches — create PR branch and open GitHub PR

Usage:
    python patch_integrate.py --approval-file /path/to/approval.json
    python patch_integrate.py --date 2026-03-25 --approval-file /path/to/approval.json

Creates an integrate/<date>/<slug> branch from the working branch, cherry-picks
commits from the review branch, pushes to origin, and opens a GitHub PR via
the gh CLI.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

from approval import ApprovalError, validate_integration_evidence
from config import Config
from utils import GitError, ensure_clean_worktree, ensure_local_branch, git_run, today_str, validate_staging_date


def _derive_integrate_branch(review_branch: str, cfg: Config) -> str:
    """Derive integrate/<date>/<slug> from review/<date>/<slug>."""
    parts = review_branch.split("/", 1)
    suffix = parts[1] if len(parts) == 2 else review_branch
    return f"{cfg.integrate_branch_prefix}/{suffix}"


def _cherry_pick_args(repo: Path, commit_sha: str) -> tuple[str, ...]:
    """Use the first-parent diff when a reviewed branch contains a merge commit."""
    parents = git_run("rev-list", "--parents", "-n", "1", commit_sha, cwd=repo).stdout.split()
    if len(parents) > 2:
        return ("-m", "1", commit_sha)
    return (commit_sha,)


def _create_github_pr(
    repo: Path,
    integrate_branch: str,
    base_branch: str,
    applied: list[dict],
    approval: dict,
) -> str | None:
    """Create a GitHub PR via gh CLI. Returns PR URL or None on failure."""
    title = f"Integrate: {applied[0]['subject'][:70]}" if applied else "Integrate patches"
    lines = ["Integrated patches via patch-pipeline:", ""]
    for c in applied:
        lines.append(f"- `{c['hash']}` {c['subject']}")
    lines.extend([
        "",
        f"Approval: {approval['sender']}",
        f"Approval message ID: `{approval['message_id']}`",
        f"Approved at: {approval['approved_at']}",
    ])
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


def integrate_patches(staging_dir: Path, cfg: Config, approval_file: Path) -> None:
    """Create integrate branch, cherry-pick review commits, push, open GitHub PR."""
    repo = cfg.repo_path

    try:
        evidence = validate_integration_evidence(repo, staging_dir, approval_file)
    except (ApprovalError, GitError, ValueError) as exc:
        print(f"❌ Integration blocked: {exc}")
        sys.exit(1)
    recorded_base = evidence["apply"].get("base")
    base_branch = recorded_base if isinstance(recorded_base, str) and recorded_base else cfg.resolved_working_branch

    review_branch = evidence["review_branch"]
    commit_shas = evidence["commit_shas"]
    approval = evidence["approval"]
    commit_records = []
    for commit_sha in commit_shas:
        subject = git_run("log", "-1", "--format=%s", commit_sha, cwd=repo).stdout.strip()
        parents = git_run("rev-list", "--parents", "-n", "1", commit_sha, cwd=repo).stdout.split()
        commit_records.append({"hash": commit_sha, "subject": subject, "merge": len(parents) > 2})

    # Derive integrate branch name
    integrate_branch = _derive_integrate_branch(review_branch, cfg)

    print(f"\n{'─' * 60}")
    print(f"Integration: {review_branch} → {integrate_branch} → PR → {base_branch}")
    print(f"Commits to cherry-pick: {len(commit_records)}")
    for commit in commit_records:
        print(f"  {commit['hash']}  {commit['subject'][:60]}")
    print(f"Approval: {approval['sender']} / {approval['message_id']}")
    print(f"{'─' * 60}\n")

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

    # Cherry-pick every commit unique to the reviewed branch, including cleanup commits.
    print(f"🍒 Cherry-picking {len(commit_records)} commit(s)...\n")
    picked = []

    for i, commit in enumerate(commit_records, 1):
        hash_val = commit["hash"]
        print(f"  [{i}/{len(commit_records)}] {hash_val} {commit['subject'][:50]}...", end=" ")

        cherry_pick_args = _cherry_pick_args(repo, hash_val)
        result = git_run("cherry-pick", *cherry_pick_args, cwd=repo, check=False)

        if result.returncode != 0:
            print("❌ CONFLICT")
            print(f"\n{'─' * 60}")
            print(f"Conflict during cherry-pick of {hash_val}")
            print(f"Git output:\n{result.stderr}")
            print(f"\nTo resolve:")
            print(f"  1. Fix conflicts on the integrate branch")
            print(f"  2. git add <files>")
            print(f"  3. git cherry-pick --continue")
            git_run("cherry-pick", "--abort", cwd=repo, check=False)
            git_run("checkout", original_branch, cwd=repo, check=False)
            git_run("branch", "-D", integrate_branch, cwd=repo, check=False)
            print("Cherry-pick aborted and integrate branch cleaned up.")
            sys.exit(1)

        print("✅")
        picked.append(commit)

    if len(picked) != len(commit_records):
        print(f"\n❌ Cherry-picked {len(picked)}/{len(commit_records)} commits")
        sys.exit(1)

    print(f"\n✅ All {len(picked)} commits cherry-picked to {integrate_branch}!")

    # Push integrate branch to origin
    print(f"\n📤 Pushing {integrate_branch} to origin...")
    push_result = git_run("push", "origin", integrate_branch, cwd=repo, check=False)
    if push_result.returncode != 0:
        print(f"❌ Push failed: {push_result.stderr.strip()}")
        print(f"   Push manually: git push origin {integrate_branch}")
        sys.exit(1)
    print("✅ Branch pushed.")

    # Open GitHub PR via gh CLI
    print(f"\n🔗 Creating GitHub PR ({integrate_branch} → {base_branch})...")
    pr_url = None
    if not shutil.which("gh"):
        print("⚠️  gh CLI not found. Create the PR manually:")
        print(f"   gh pr create --base {base_branch} --head {integrate_branch}")
    else:
        pr_url = _create_github_pr(repo, integrate_branch, base_branch, picked, approval)
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
        "approval": {
            "sender": approval["sender"],
            "message_id": approval["message_id"],
            "approved_at": approval["approved_at"],
        },
    }
    integrate_file = staging_dir / "integrate_data.json"
    with open(integrate_file, "w") as f:
        json.dump(integrate_data, f, indent=2)
    print(f"\n💾 Integrate data saved to {integrate_file}")

    print(f"\n{'─' * 60}")
    if pr_url:
        print("✅ Integration complete; PR created.")
        print(f"   PR: {pr_url}")
    else:
        print("⚠️  Integration branch ready; PR creation is pending.")
    print(f"   Branch: {integrate_branch}")
    print(f"   Target: {base_branch}")


def main():
    parser = argparse.ArgumentParser(description="Integrate blessed patches via PR branch")
    parser.add_argument("--date", default=today_str(), help="Staging date (default: today)")
    parser.add_argument("--repo", help="Path to git repo (default: cwd)")
    parser.add_argument("--approval-file", required=True,
                        help="JSON approval record exported from the approval email")
    args = parser.parse_args()

    try:
        validate_staging_date(args.date)
    except ValueError as exc:
        print(f"❌ {exc}")
        sys.exit(1)
    cfg = Config.load(args.repo)
    staging = cfg.staging_path / args.date

    if not staging.is_dir():
        print(f"❌ No staged patches for {args.date}")
        sys.exit(1)

    integrate_patches(staging, cfg, Path(args.approval_file).resolve())


if __name__ == "__main__":
    main()
