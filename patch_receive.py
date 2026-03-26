#!/usr/bin/env python3
"""
Step 1: Receive, validate, and review patches

Usage:
    python patch_receive.py /path/to/shared-folder/release-name/2026-03-26/
    python patch_receive.py ./local-patches/
    python patch_receive.py ./local-patches/ --date 2026-03-25   # stage under specific date
    python patch_receive.py ./local-patches/ --force              # overwrite existing session

Validates each .patch file (must be git format-patch output), shows a diff summary
with static checks, and stages patches locally. Absorbs the review step.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

from config import Config
from utils import (
    format_table,
    list_patches,
    parse_patch_header,
    today_str,
    validate_format_patch,
)

BINARY_EXTS = {".bin", ".exe", ".dll", ".o", ".obj", ".rom", ".fd", ".cap"}


def _static_checks(info: dict, cfg: Config) -> list[str]:
    warnings = []
    for f in info["files"]:
        if Path(f).suffix.lower() in BINARY_EXTS:
            warnings.append(f"Binary file: {f}")
    if cfg.allowed_path_prefixes:
        for f in info["files"]:
            if not any(f.startswith(p) for p in cfg.allowed_path_prefixes):
                warnings.append(f"Outside allowed paths: {f}")
    return warnings


def receive_patches(source_dir: Path, cfg: Config, date: str | None = None, force: bool = False) -> list[dict]:
    """Validate, review, and stage patches from source_dir."""
    patches = list_patches(source_dir)
    if not patches:
        print(f"❌ No .patch files found in {source_dir}")
        sys.exit(1)

    print(f"Found {len(patches)} patch file(s) in {source_dir}\n")

    staging = cfg.staging_path / (date or today_str())

    # Guard: don't silently overwrite an existing session
    if staging.exists() and list_patches(staging) and not force:
        print(f"❌ Staging dir already has patches for {staging.name}.")
        print(f"   Use --force to overwrite, or --date <other-date> to use a different slot.")
        sys.exit(1)

    staging.mkdir(parents=True, exist_ok=True)

    valid_patches = []
    all_warnings: list[str] = []
    reviewer_notes: dict[str, str] = {}
    errors = []

    for i, p in enumerate(patches, 1):
        ok, reason = validate_format_patch(p)
        if not ok:
            errors.append((p.name, reason))
            continue

        size_kb = p.stat().st_size / 1024
        if size_kb > cfg.max_patch_size_kb:
            errors.append((p.name, f"Too large: {size_kb:.0f} KB"))
            continue

        info = parse_patch_header(p)
        warnings = _static_checks(info, cfg)

        print(f"{'─' * 60}")
        print(f"Patch {i}: {info['subject']}")
        print(f"  Author : {info['author']}")
        print(f"  Changes: {info['files_changed']} file(s)  +{info['insertions']}/-{info['deletions']}")
        if info["files"]:
            for f in info["files"][:10]:
                print(f"    • {f}")
            if len(info["files"]) > 10:
                print(f"    ... and {len(info['files']) - 10} more")
        if warnings:
            for w in warnings:
                print(f"  ⚠️  {w}")
            all_warnings.extend(warnings)

        try:
            note = input("  📝 Note (Enter to skip): ").strip()
        except (EOFError, KeyboardInterrupt):
            note = ""
        if note:
            reviewer_notes[p.name] = note

        valid_patches.append(info)
        shutil.copy2(p, staging / p.name)

    print(f"\n{'─' * 60}")
    if valid_patches:
        rows = [[str(i), v["subject"][:55], str(v["files_changed"]),
                 f"+{v['insertions']}/-{v['deletions']}"]
                for i, v in enumerate(valid_patches, 1)]
        print(format_table(["#", "Subject", "Files", "+/-"], rows))
        print(f"\n✅ {len(valid_patches)} patch(es) staged to {staging}")

    if errors:
        print(f"\n⚠️  {len(errors)} patch(es) skipped:")
        for name, reason in errors:
            print(f"  • {name}: {reason}")

    # Save review data for report
    review_data = {"patches": valid_patches, "all_warnings": all_warnings,
                   "reviewer_notes": reviewer_notes}
    (staging / "review_data.json").write_text(json.dumps(review_data, indent=2))

    return valid_patches


def main():
    parser = argparse.ArgumentParser(description="Receive, validate, and review patches")
    parser.add_argument("source", help="Directory containing .patch files")
    parser.add_argument("--repo", help="Path to git repo (default: cwd)")
    parser.add_argument("--date", default=None, help="Override staging date (default: today)")
    parser.add_argument("--force", action="store_true", help="Overwrite existing staged session")
    args = parser.parse_args()

    cfg = Config.load(args.repo)
    source = Path(args.source).resolve()

    if not source.is_dir():
        print(f"❌ Source directory does not exist: {source}")
        sys.exit(1)

    receive_patches(source, cfg, date=args.date, force=args.force)


if __name__ == "__main__":
    main()
