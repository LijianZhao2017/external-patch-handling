#!/usr/bin/env python3
"""
Step 4: Run tests on the applied patches

Usage:
    python patch_test.py                          # test today's staged patches
    python patch_test.py --date 2026-03-25
    python patch_test.py --skip-build             # skip build check

Runs build check, unit tests, and prompts for silicon test results.
"""

from __future__ import annotations

import argparse
import json
import shlex
import subprocess
import sys
from pathlib import Path

from config import Config
from utils import today_str


def run_command(label: str, command: str, cwd: Path) -> dict:
    """Run a command and return structured result."""
    if not command:
        return {"test": label, "result": "SKIPPED", "notes": "No command configured"}

    print(f"  🔧 {label}: running `{command}`...")

    try:
        result = subprocess.run(
            shlex.split(command),
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=600,  # 10 min timeout
        )

        if result.returncode == 0:
            output_lines = result.stdout.strip().split("\n")
            summary = "\n".join(output_lines[-5:]) if len(output_lines) > 5 else result.stdout.strip()
            print(f"     ✅ PASS")
            return {"test": label, "result": "PASS", "notes": summary[:300]}
        else:
            # Use last 500 chars of stderr (most relevant for build failures);
            # fall back to stdout if stderr is empty
            combined = (result.stderr or result.stdout or "").strip()
            snippet = combined[-500:] if len(combined) > 500 else combined
            print(f"     ❌ FAIL")
            return {"test": label, "result": "FAIL", "notes": snippet}

    except subprocess.TimeoutExpired:
        print(f"     ⏰ TIMEOUT (>10 min)")
        return {"test": label, "result": "TIMEOUT", "notes": "Command exceeded 10-minute timeout"}
    except Exception as e:
        print(f"     ❌ ERROR: {e}")
        return {"test": label, "result": "ERROR", "notes": str(e)[:200]}


def prompt_silicon_test() -> dict:
    """Prompt user for silicon test results."""
    print(f"\n  🔬 Silicon Test (manual entry):")

    try:
        result = input("     Result (PASS/FAIL/PENDING/SKIP) [PENDING]: ").strip().upper() or "PENDING"
        if result not in ("PASS", "FAIL", "PENDING", "SKIP"):
            result = "PENDING"

        notes = ""
        if result in ("PASS", "FAIL"):
            notes = input("     Notes (attach log path or brief result): ").strip()
        elif result == "PENDING":
            notes = "Silicon test not yet performed"

        attachment = ""
        if result in ("PASS", "FAIL"):
            attachment = input("     Attach result file path (Enter to skip): ").strip()

    except (EOFError, KeyboardInterrupt):
        result = "PENDING"
        notes = "Skipped by user"
        attachment = ""

    entry = {"test": "Silicon Test", "result": result, "notes": notes}
    if attachment:
        entry["attachment"] = attachment
    return entry


def run_tests(staging_dir: Path, cfg: Config, skip_build: bool = False) -> list[dict]:
    """Run all configured tests. Returns list of test results."""
    repo = cfg.repo_path

    print(f"🧪 Running tests on {repo}\n")
    results = []

    # Build check
    if skip_build:
        results.append({"test": "Build Check", "result": "SKIPPED", "notes": "Skipped by --skip-build"})
    else:
        results.append(run_command("Build Check", cfg.build_command, repo))

    # Unit tests
    results.append(run_command("Unit Test", cfg.unit_test_command, repo))

    # Silicon test (manual)
    results.append(prompt_silicon_test())

    # Print summary
    print(f"\n{'─' * 60}")
    print("Test Summary:")
    for r in results:
        icon = {"PASS": "✅", "FAIL": "❌", "SKIPPED": "⏭️", "PENDING": "⏳", "TIMEOUT": "⏰", "ERROR": "💥"}.get(r["result"], "❓")
        print(f"  {icon} {r['test']}: {r['result']}")

    # Save test results
    test_file = staging_dir / "test_data.json"
    with open(test_file, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\n💾 Test data saved to {test_file}")

    return results


def main():
    parser = argparse.ArgumentParser(description="Run tests on applied patches")
    parser.add_argument("--date", default=today_str(), help="Staging date (default: today)")
    parser.add_argument("--repo", help="Path to git repo (default: cwd)")
    parser.add_argument("--skip-build", action="store_true", help="Skip build check")
    args = parser.parse_args()

    cfg = Config.load(args.repo)
    staging = cfg.staging_path / args.date

    if not staging.is_dir():
        print(f"❌ No staged patches for {args.date}")
        sys.exit(1)

    run_tests(staging, cfg, args.skip_build)


if __name__ == "__main__":
    main()
