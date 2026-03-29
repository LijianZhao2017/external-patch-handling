"""Tests for utils.py — patch parsing, validation, formatting helpers."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "python"))

import pytest
from utils import (
    format_table,
    parse_patch_header,
    slugify,
    validate_format_patch,
)

# ── Fixtures ──────────────────────────────────────────────────────────────

VALID_PATCH = """\
From abc1234 Mon Sep 17 00:00:00 2001
From: Jane Doe <jane@example.com>
Date: Thu, 26 Mar 2026 10:00:00 +0000
Subject: [PATCH 1/2] BHS: fix mrc timing margin

Add margin field to mrc_train for BHS-B0 timing closure.

---
 Silicon/BHS/mrc.c | 2 +-
 1 file changed, 1 insertion(+), 1 deletion(-)

diff --git a/Silicon/BHS/mrc.c b/Silicon/BHS/mrc.c
index abc..def 100644
--- a/Silicon/BHS/mrc.c
+++ b/Silicon/BHS/mrc.c
@@ -10,6 +10,7 @@ void mrc_train() {
     int delay = 100;
+    int margin = 5;
-    return;
+    return margin;
 }
--
2.40.0
"""

INVALID_PATCH_NO_FROM = """\
Subject: [PATCH] something
Date: Thu, 26 Mar 2026 10:00:00 +0000

diff --git a/foo.c b/foo.c
"""

INVALID_PATCH_NO_DIFF = """\
From abc1234 Mon Sep 17 00:00:00 2001
From: Jane Doe <jane@example.com>
Subject: [PATCH] just a note

This patch has no diff content.
"""

RENAME_PATCH = """\
From abc9999 Mon Sep 17 00:00:00 2001
From: Dev <dev@example.com>
Date: Thu, 26 Mar 2026 11:00:00 +0000
Subject: [PATCH] rename mrc.c to mrc_core.c

---
 Silicon/BHS/{mrc.c => mrc_core.c} | 0
 1 file changed

diff --git a/Silicon/BHS/mrc.c b/Silicon/BHS/mrc_core.c
similarity index 100%
rename from Silicon/BHS/mrc.c
rename to Silicon/BHS/mrc_core.c
"""


# ── validate_format_patch ────────────────────────────────────────────────

def test_validate_valid_patch(tmp_path):
    p = tmp_path / "0001.patch"
    p.write_text(VALID_PATCH)
    ok, reason = validate_format_patch(p)
    assert ok is True
    assert reason == "OK"


def test_validate_missing_from_header(tmp_path):
    p = tmp_path / "bad.patch"
    p.write_text(INVALID_PATCH_NO_FROM)
    ok, reason = validate_format_patch(p)
    assert ok is False
    assert "From" in reason


def test_validate_missing_diff(tmp_path):
    p = tmp_path / "nodiff.patch"
    p.write_text(INVALID_PATCH_NO_DIFF)
    ok, reason = validate_format_patch(p)
    assert ok is False
    assert "diff" in reason.lower()


def test_validate_nonexistent_file(tmp_path):
    ok, reason = validate_format_patch(tmp_path / "missing.patch")
    assert ok is False


# ── parse_patch_header ───────────────────────────────────────────────────

def test_parse_subject_strips_patch_prefix(tmp_path):
    p = tmp_path / "0001.patch"
    p.write_text(VALID_PATCH)
    info = parse_patch_header(p)
    assert info["subject"] == "BHS: fix mrc timing margin"
    assert "PATCH" not in info["subject"]


def test_parse_author(tmp_path):
    p = tmp_path / "0001.patch"
    p.write_text(VALID_PATCH)
    info = parse_patch_header(p)
    assert "Jane Doe" in info["author"]


def test_parse_files(tmp_path):
    p = tmp_path / "0001.patch"
    p.write_text(VALID_PATCH)
    info = parse_patch_header(p)
    assert "Silicon/BHS/mrc.c" in info["files"]


def test_parse_rename_patch(tmp_path):
    p = tmp_path / "rename.patch"
    p.write_text(RENAME_PATCH)
    ok, _ = validate_format_patch(p)
    assert ok is True  # rename patches have diff --git and From header
    info = parse_patch_header(p)
    assert len(info["files"]) >= 1


# ── slugify ──────────────────────────────────────────────────────────────

def test_slugify_normal():
    assert slugify("BHS: fix mrc timing") == "bhs-fix-mrc-timing"


def test_slugify_empty_returns_unnamed():
    assert slugify("") == "unnamed"
    assert slugify("---!!!---") == "unnamed"


def test_slugify_max_len():
    result = slugify("a" * 100)
    assert len(result) <= 50


def test_slugify_special_chars():
    result = slugify("Fix [PATCH 1/3] weird: chars & symbols!")
    assert all(c.isalnum() or c == "-" for c in result)


# ── format_table ─────────────────────────────────────────────────────────

def test_format_table_basic():
    result = format_table(["Name", "Value"], [["foo", "bar"], ["baz", "qux"]])
    assert "| Name" in result
    assert "| foo" in result


def test_format_table_short_row_no_crash():
    """Rows shorter than headers must not crash or corrupt output."""
    result = format_table(["A", "B", "C"], [["x"]])  # row has only 1 cell
    assert "| x" in result
    lines = result.split("\n")
    # All lines should have the same number of | separators
    counts = [line.count("|") for line in lines if line.strip()]
    assert len(set(counts)) == 1, f"Inconsistent column counts: {counts}"


def test_format_table_empty_rows():
    result = format_table(["A", "B"], [])
    assert "| A" in result  # header still present
