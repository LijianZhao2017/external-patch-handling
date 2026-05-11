"""Tests for patch_report.py — Markdown and HTML report generation."""

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "python"))

import patch_report
from config import Config


def _write_json(path, data):
    path.write_text(json.dumps(data))


def _populate_staging(staging):
    staging.mkdir(parents=True)
    _write_json(
        staging / "review_data.json",
        {
            "patches": [
                {
                    "subject": "Fix <timing> margin",
                    "author": "Jane & Dev",
                    "files_changed": 2,
                    "insertions": 5,
                    "deletions": 1,
                }
            ],
            "all_warnings": ["Path <bad> requires review"],
            "reviewer_notes": {"0001.patch": "Looks & behaves correctly"},
        },
    )
    _write_json(
        staging / "apply_data.json",
        {
            "branch": "review/2026-03-25/fix-timing",
            "base": "main",
            "applied": [{"hash": "abc1234", "subject": "Fix <timing> margin"}],
            "total": 1,
        },
    )
    _write_json(
        staging / "check_data.json",
        {
            "overall": "PASS",
            "summary": {"match": 1, "partial": 0, "mismatch": 0, "missing": 0, "extra": 0},
            "files": [{"file": "Silicon/BHS/mrc<core>.c", "status": "MATCH", "similarity": 1.0}],
        },
    )
    _write_json(
        staging / "test_data.json",
        [{"test": "unit & build", "result": "PASS", "notes": "ok <safe>"}],
    )


def test_generate_html_report_keeps_report_sections_and_escapes_html(tmp_path, monkeypatch):
    monkeypatch.delenv("PATCH_PIPELINE_RELEASE", raising=False)
    cfg = Config.load(repo_path=tmp_path)
    staging = tmp_path / ".patch-staging" / "2026-03-25"
    _populate_staging(staging)

    report = patch_report.generate_html_report(staging, cfg)

    assert report.startswith("<!doctype html>")
    assert "<h2>Patches Received</h2>" in report
    assert "<h2>Review Notes</h2>" in report
    assert "<h2>Apply Result</h2>" in report
    assert "<h2>Functional Equivalence Check</h2>" in report
    assert "<h2>Test Results</h2>" in report
    assert "<h2>Reviewer Recommendation</h2>" in report
    assert "Fix &lt;timing&gt; margin" in report
    assert "Jane &amp; Dev" in report
    assert "mrc&lt;core&gt;.c" in report
    assert "ok &lt;safe&gt;" in report


def test_generate_html_report_handles_null_warnings(tmp_path, monkeypatch):
    monkeypatch.delenv("PATCH_PIPELINE_RELEASE", raising=False)
    cfg = Config.load(repo_path=tmp_path)
    staging = tmp_path / ".patch-staging" / "2026-03-25"
    _populate_staging(staging)
    (staging / "review_data.json").write_text(
        json.dumps({"patches": [], "all_warnings": None, "reviewer_notes": {}})
    )

    report = patch_report.generate_html_report(staging, cfg)

    assert "<span>Warnings</span><span class=\"badge good\">0</span>" in report


def test_main_writes_markdown_and_html_reports(tmp_path, monkeypatch):
    monkeypatch.delenv("PATCH_PIPELINE_RELEASE", raising=False)
    staging = tmp_path / ".patch-staging" / "2026-03-25"
    _populate_staging(staging)
    monkeypatch.setattr(
        sys,
        "argv",
        ["patch_report.py", "--repo", str(tmp_path), "--date", "2026-03-25"],
    )

    patch_report.main()

    markdown_report = staging / "REVIEW_REPORT.md"
    html_report = staging / "REVIEW_REPORT.html"
    assert markdown_report.exists()
    assert html_report.exists()
    assert "# Patch Review Report" in markdown_report.read_text()
    assert "<!doctype html>" in html_report.read_text()


def test_main_writes_html_next_to_custom_markdown_output(tmp_path, monkeypatch):
    monkeypatch.delenv("PATCH_PIPELINE_RELEASE", raising=False)
    staging = tmp_path / ".patch-staging" / "2026-03-25"
    _populate_staging(staging)
    output = tmp_path / "reports" / "custom-review.md"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "patch_report.py",
            "--repo",
            str(tmp_path),
            "--date",
            "2026-03-25",
            "--output",
            str(output),
        ],
    )

    patch_report.main()

    assert output.exists()
    assert (output.parent / "custom-review.html").exists()
