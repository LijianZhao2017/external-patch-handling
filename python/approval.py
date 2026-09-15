#!/usr/bin/env python3
"""Validate the evidence required before integration."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from utils import GitError, git_run, normalize_check_data, normalize_test_data


class ApprovalError(Exception):
    """Raised when an integration approval or technical gate is invalid."""


def _load_json(path: Path) -> object:
    try:
        with path.open() as handle:
            return json.load(handle)
    except OSError as exc:
        raise ApprovalError(f"Cannot read {path}: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise ApprovalError(f"Invalid JSON in {path}: {exc}") from exc


def _review_commit_shas(repo: Path, apply_data: dict) -> tuple[str, list[str]]:
    review_branch = apply_data.get("branch")
    if not review_branch:
        raise ApprovalError("apply_data.json has no review branch")
    if apply_data.get("failed"):
        raise ApprovalError("Patch application is incomplete; resolve and rerun the apply step")

    base_commit = apply_data.get("base_commit")
    if not base_commit:
        applied = apply_data.get("applied", [])
        if not applied:
            raise ApprovalError("apply_data.json has no applied commits")
        parent = git_run("rev-parse", f"{applied[0]['hash']}^", cwd=repo, check=False)
        if parent.returncode != 0:
            raise ApprovalError("Cannot determine the review branch base commit")
        base_commit = parent.stdout.strip()

    base = git_run("rev-parse", f"{base_commit}^{{commit}}", cwd=repo, check=False)
    if base.returncode != 0:
        raise ApprovalError(f"Review base commit is not available: {base_commit}")
    base_commit = base.stdout.strip()

    branch = git_run("rev-parse", f"{review_branch}^{{commit}}", cwd=repo, check=False)
    if branch.returncode != 0:
        raise ApprovalError(f"Review branch is not available: {review_branch}")

    ancestry = git_run(
        "merge-base", "--is-ancestor", base_commit, review_branch,
        cwd=repo, check=False,
    )
    if ancestry.returncode != 0:
        raise ApprovalError(
            f"Review branch {review_branch} is not based on recorded commit {base_commit}"
        )

    commits = git_run(
        "rev-list", "--reverse", "--first-parent",
        f"{base_commit}..{review_branch}", cwd=repo,
    ).stdout.splitlines()
    if not commits:
        raise ApprovalError("Review branch has no commits to integrate")
    return base_commit, commits


def _validate_test_results(path: Path) -> list[dict]:
    tests = normalize_test_data(_load_json(path))
    allowed = {"PASS", "FAIL", "SKIPPED", "PENDING", "TIMEOUT", "ERROR"}
    for entry in tests:
        result = str(entry["result"]).upper()
        if result == "SKIP":
            result = "SKIPPED"
        if result not in allowed:
            raise ApprovalError(f"Invalid test result in {path}: {result}")
        entry["result"] = result
    required_tests = {"Build Check", "Unit Test", "Silicon Test"}
    names = {str(entry["test"]) for entry in tests}
    missing = required_tests - names
    if missing:
        raise ApprovalError(f"Test evidence is incomplete: missing {', '.join(sorted(missing))}")
    failures = [entry["test"] for entry in tests if entry["result"] in {"FAIL", "TIMEOUT", "ERROR"}]
    if failures:
        raise ApprovalError(f"Automated tests are not acceptable: {', '.join(failures)}")
    automated_pending = [
        entry["test"] for entry in tests
        if entry["test"] in {"Build Check", "Unit Test"}
        and entry["result"] not in {"PASS", "SKIPPED"}
    ]
    if automated_pending:
        raise ApprovalError(
            f"Automated tests must be PASS or SKIPPED: {', '.join(automated_pending)}"
        )
    return tests


def _validate_approval(
    approval_path: Path,
    staging_dir: Path,
    review_branch: str,
    commit_shas: list[str],
) -> dict:
    raw = _load_json(approval_path)
    if not isinstance(raw, dict):
        raise ApprovalError("Approval file must contain a JSON object")

    required = ("decision", "approval_type", "message_id", "sender", "approved_at")
    missing = [field for field in required if not str(raw.get(field, "")).strip()]
    if missing:
        raise ApprovalError(f"Approval file is missing: {', '.join(missing)}")
    if str(raw["decision"]).upper() != "APPROVED":
        raise ApprovalError("Approval decision must be APPROVED")
    if str(raw["approval_type"]).lower() != "email":
        raise ApprovalError("approval_type must be email")
    if raw.get("review_branch") != review_branch:
        raise ApprovalError("Approval review_branch does not match apply_data.json")

    approved_commits = raw.get("commit_shas")
    if not isinstance(approved_commits, list) or approved_commits != commit_shas:
        raise ApprovalError("Approval commit_shas do not exactly match the review branch")
    if any(not isinstance(sha, str) or not re.fullmatch(r"[0-9a-f]{40}", sha) for sha in approved_commits):
        raise ApprovalError("Approval commit_shas must contain full 40-character commit hashes")

    report_file = raw.get("report_file")
    report_hash = raw.get("report_sha256")
    if not isinstance(report_file, str) or not report_file:
        raise ApprovalError("Approval must identify the reviewed report_file")
    if report_file not in {"REVIEW_REPORT.html", "REVIEW_REPORT.md"}:
        raise ApprovalError("report_file must be REVIEW_REPORT.html or REVIEW_REPORT.md")
    if not isinstance(report_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", report_hash):
        raise ApprovalError("Approval report_sha256 must be a 64-character SHA-256 digest")
    report_path = (staging_dir / report_file).resolve()
    try:
        report_path.relative_to(staging_dir.resolve())
    except ValueError as exc:
        raise ApprovalError("Approval report_file must stay inside the staging directory") from exc
    if not report_path.is_file():
        raise ApprovalError(f"Reviewed report does not exist: {report_file}")
    actual_hash = hashlib.sha256(report_path.read_bytes()).hexdigest()
    if actual_hash != report_hash.lower():
        raise ApprovalError("Reviewed report hash does not match the approval record")

    return raw


def validate_integration_evidence(
    repo: Path,
    staging_dir: Path,
    approval_path: Path,
) -> dict:
    """Validate technical gates and approval scope for one integration run."""
    apply_path = staging_dir / "apply_data.json"
    check_path = staging_dir / "check_data.json"
    test_path = staging_dir / "test_data.json"
    for path in (apply_path, check_path, test_path):
        if not path.is_file():
            raise ApprovalError(f"Required evidence is missing: {path.name}")

    apply_data = _load_json(apply_path)
    if not isinstance(apply_data, dict):
        raise ApprovalError("apply_data.json must contain an object")
    check_data = normalize_check_data(_load_json(check_path))
    if check_data["overall"] != "PASS":
        raise ApprovalError("Equivalence check is not PASS; resolve PARTIAL, MISMATCH, MISSING, or EXTRA files")
    tests = _validate_test_results(test_path)
    base_commit, commit_shas = _review_commit_shas(repo, apply_data)
    review_branch = apply_data["branch"]
    approval = _validate_approval(approval_path, staging_dir, review_branch, commit_shas)

    record = dict(approval)
    record["verification"] = {
        "review_branch": review_branch,
        "base_commit": base_commit,
        "review_commit_shas": commit_shas,
        "equivalence": check_data["overall"],
        "test_results": tests,
        "report_file": approval["report_file"],
        "report_sha256": approval["report_sha256"].lower(),
    }
    (staging_dir / "approval_data.json").write_text(json.dumps(record, indent=2) + "\n")
    return {
        "apply": apply_data,
        "check": check_data,
        "tests": tests,
        "approval": record,
        "base_commit": base_commit,
        "review_branch": review_branch,
        "commit_shas": commit_shas,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate patch integration evidence")
    parser.add_argument("--repo", default=".", help="Path to the target git repo")
    parser.add_argument("--staging", required=True, help="Staging directory for this review")
    parser.add_argument("--approval-file", required=True, help="JSON approval record exported from the approval email")
    args = parser.parse_args()

    try:
        evidence = validate_integration_evidence(
            Path(args.repo).resolve(),
            Path(args.staging).resolve(),
            Path(args.approval_file).resolve(),
        )
    except (ApprovalError, GitError, ValueError) as exc:
        print(f"❌ Integration evidence rejected: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"✅ Integration evidence accepted for {evidence['review_branch']}")


if __name__ == "__main__":
    main()
