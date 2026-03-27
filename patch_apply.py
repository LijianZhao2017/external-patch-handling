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
import tempfile
from pathlib import Path

from config import Config
from utils import (
    GitError,
    ensure_clean_worktree,
    ensure_local_branch,
    detect_patch_root_prefix,
    git_run,
    list_patches,
    parse_patch_header,
    rewrite_patch_with_stripped_prefix,
    slugify,
    today_str,
)


def _prepare_patch_for_repo(patch_path: Path, repo: Path, info: dict) -> tuple[Path, str | None]:
    """Prepare a patch file for the target repo without mutating the source patch."""
    prefix = detect_patch_root_prefix(info.get("files", []), repo)
    if not prefix:
        return patch_path, None

    rewritten = rewrite_patch_with_stripped_prefix(
        patch_path.read_text(errors="replace"),
        prefix,
    )
    fd, temp_name = tempfile.mkstemp(prefix="patch-pipeline-", suffix=".patch")
    temp_path = Path(temp_name)
    with open(fd, "w") as f:
        f.write(rewritten)
    return temp_path, prefix


def _diagnose_apply_failure(repo: Path, patch_path: Path) -> str:
    result = git_run("apply", "--check", str(patch_path), cwd=repo, check=False)
    return (result.stderr or result.stdout or "").strip()


def apply_patches(staging_dir: Path, cfg: Config) -> dict:
    """Apply all patches from staging to a new review branch."""
    repo = cfg.repo_path
    base_branch = cfg.resolved_working_branch
    patches = list_patches(staging_dir)
    if not patches:
        print(f"❌ No patches in {staging_dir}")
        sys.exit(1)

    # Ensure clean worktree
    try:
        ensure_clean_worktree(repo, ignored_paths=[cfg.staging_dir])
    except GitError as e:
        print(f"❌ {e}")
        sys.exit(1)

    # Determine branch name from first patch subject
    first_info = parse_patch_header(patches[0])
    slug = slugify(first_info["subject"])
    date_str = staging_dir.name  # e.g. "2026-03-26"
    branch_name = f"{cfg.review_branch_prefix}/{date_str}/{slug}"

    print(f"📦 Applying {len(patches)} patch(es) to branch: {branch_name}")
    print(f"   Base: {base_branch}\n")

    # Checkout working branch and create review branch
    original_branch = git_run("rev-parse", "--abbrev-ref", "HEAD", cwd=repo).stdout.strip()
    try:
        ensure_local_branch(repo, base_branch)
        git_run("checkout", base_branch, cwd=repo)
    except GitError as e:
        print(f"❌ {e}")
        sys.exit(1)

    result = git_run("checkout", "-b", branch_name, cwd=repo, check=False)
    if result.returncode != 0:
        # Restore original branch before exiting
        git_run("checkout", original_branch, cwd=repo, check=False)
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
        apply_patch, stripped_prefix = _prepare_patch_for_repo(patch_path, repo, info)
        print(f"  [{i}/{len(patches)}] Applying: {info['subject'][:60]}...", end=" ")

        try:
            result = git_run(
                "am", "--3way", str(apply_patch),
                cwd=repo,
                check=False,
            )
        finally:
            if apply_patch != patch_path and apply_patch.exists():
                apply_patch.unlink()

        if result.returncode != 0:
            print("❌ CONFLICT")
            if stripped_prefix is None:
                apply_check_error = _diagnose_apply_failure(repo, patch_path)
            else:
                dryrun_patch, _ = _prepare_patch_for_repo(patch_path, repo, info)
                try:
                    apply_check_error = _diagnose_apply_failure(repo, dryrun_patch)
                finally:
                    if dryrun_patch != patch_path and dryrun_patch.exists():
                        dryrun_patch.unlink()
            print(f"\n{'─' * 60}")
            print(f"Conflict while applying patch {i}: {patch_path.name}")
            print(f"Git output:\n{result.stderr}")
            if stripped_prefix:
                print(f"Detected repo-root prefix mismatch: stripped leading '{stripped_prefix}/' for diagnostics.")
            if apply_check_error:
                print(f"Plain apply check:\n{apply_check_error}")
            print(f"\nTo resolve manually:")
            print(f"  1. Fix conflicts in the listed files")
            print(f"  2. git add <resolved-files>")
            print(f"  3. git am --continue")
            print(f"  Or to abort: git am --abort && git checkout {base_branch} && git branch -D {branch_name}")
            failed = {
                "patch": patch_path.name,
                "index": i,
                "error": result.stderr,
                "stripped_prefix": stripped_prefix,
                "apply_check_error": apply_check_error,
            }
            break

        print("✅")

        # Get the commit hash just created
        log = git_run("log", "-1", "--format=%H %s", cwd=repo)
        parts = log.stdout.strip().split(" ", 1)
        applied.append({"hash": parts[0][:12], "subject": parts[1] if len(parts) > 1 else ""})

    # Result summary
    apply_data = {
        "branch": branch_name,
        "base": base_branch,
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
