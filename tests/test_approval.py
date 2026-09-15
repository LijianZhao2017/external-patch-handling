"""Tests for integration evidence and approval validation."""

import hashlib
import json
import os
import subprocess
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "python"))

from approval import ApprovalError, validate_integration_evidence
from utils import normalize_check_data, normalize_test_data


def _git(cwd, *args):
    return subprocess.run(
        ["git", "--no-pager", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path):
    _git(path, "init", "-b", "main")
    _git(path, "config", "user.name", "Test User")
    _git(path, "config", "user.email", "test@example.com")
    (path / "file.txt").write_text("base\n")
    _git(path, "add", "file.txt")
    _git(path, "commit", "-m", "base")


def _commit(path, content, subject):
    (path / "file.txt").write_text(content)
    _git(path, "add", "file.txt")
    _git(path, "commit", "-m", subject)
    return _git(path, "rev-parse", "HEAD").stdout.strip()


def _write_evidence(staging, base_commit, review_branch, commit_shas, check=None):
    staging.mkdir(parents=True)
    (staging / "apply_data.json").write_text(json.dumps({
        "branch": review_branch,
        "base": "main",
        "base_commit": base_commit,
        "applied": [{"hash": commit_shas[0], "subject": "patch"}],
        "failed": None,
        "total": 1,
    }))
    (staging / "check_data.json").write_text(json.dumps(check or {
        "files": [{"file": "file.txt", "status": "MATCH", "similarity": 1.0}],
    }))
    (staging / "test_data.json").write_text(json.dumps([
        {"test": "Build Check", "result": "PASS", "notes": ""},
        {"test": "Unit Test", "result": "PASS", "notes": ""},
        {"test": "Silicon Test", "result": "PENDING", "notes": ""},
    ]))
    report = staging / "REVIEW_REPORT.html"
    report.write_text("review report")
    approval = staging / "approval-input.json"
    approval.write_text(json.dumps({
        "decision": "APPROVED",
        "approval_type": "email",
        "message_id": "<message-123@example.com>",
        "sender": "sender@example.com",
        "approved_at": "2026-09-15T15:00:00+08:00",
        "review_branch": review_branch,
        "commit_shas": commit_shas,
        "report_file": "REVIEW_REPORT.html",
        "report_sha256": hashlib.sha256(report.read_bytes()).hexdigest(),
    }))
    return approval


def test_validate_integration_evidence_binds_all_review_commits(tmp_path):
    _init_repo(tmp_path)
    base_commit = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    review_branch = "review/2026-09-15/fix"
    _git(tmp_path, "checkout", "-b", review_branch)
    first = _commit(tmp_path, "patch\n", "patch")
    second = _commit(tmp_path, "patch\ncleanup\n", "cleanup")
    staging = tmp_path / ".patch-staging" / "2026-09-15"
    approval = _write_evidence(staging, base_commit, review_branch, [first, second])

    result = validate_integration_evidence(tmp_path, staging, approval)

    assert result["commit_shas"] == [first, second]
    saved = json.loads((staging / "approval_data.json").read_text())
    assert saved["verification"]["review_commit_shas"] == [first, second]


def test_validate_integration_evidence_rejects_partial_equivalence(tmp_path):
    _init_repo(tmp_path)
    base_commit = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    review_branch = "review/2026-09-15/fix"
    _git(tmp_path, "checkout", "-b", review_branch)
    commit = _commit(tmp_path, "patch\n", "patch")
    staging = tmp_path / ".patch-staging" / "2026-09-15"
    approval = _write_evidence(
        staging,
        base_commit,
        review_branch,
        [commit],
        check={"files": [{"file": "file.txt", "status": "PARTIAL", "similarity": 0.5}]},
    )

    with pytest.raises(ApprovalError, match="Equivalence"):
        validate_integration_evidence(tmp_path, staging, approval)


def test_legacy_staging_schemas_are_normalized():
    tests = normalize_test_data({
        "build_pass": True,
        "test_pass": False,
        "silicon_result": "PENDING",
        "build_log": "/tmp/build.log",
        "test_log": "/tmp/test.log",
    })
    assert [entry["result"] for entry in tests] == ["PASS", "FAIL", "PENDING"]

    check = normalize_check_data({
        "results": ["MATCH:file.txt", "EXTRA:generated.txt"],
    })
    assert check["summary"] == {"match": 1, "partial": 0, "mismatch": 0, "missing": 0, "extra": 1}
    assert check["overall"] == "NEEDS REVIEW"
