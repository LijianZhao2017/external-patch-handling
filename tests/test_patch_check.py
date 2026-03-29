"""Tests for patch_check.py — functional equivalence logic."""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "python"))

import pytest
from patch_check import _parse_diff_into_files, _token_similarity, _classify


# ── _parse_diff_into_files ────────────────────────────────────────────────

SIMPLE_DIFF = """\
diff --git a/mrc.c b/mrc.c
index abc..def 100644
--- a/mrc.c
+++ b/mrc.c
@@ -10,6 +10,7 @@ void mrc_train() {
     int delay = 100;
+    int margin = 5;
-    return;
+    return margin;
 }
"""

TWO_FILE_DIFF = """\
diff --git a/mrc.c b/mrc.c
index abc..def 100644
--- a/mrc.c
+++ b/mrc.c
@@ -1,3 +1,4 @@
+    int margin = 5;
-    int old = 0;
diff --git a/timing.c b/timing.c
index 000..111 100644
--- a/timing.c
+++ b/timing.c
@@ -5,3 +5,4 @@
+    int offset = 8;
"""

RENAME_DIFF = """\
diff --git a/old.c b/new.c
similarity index 100%
rename from old.c
rename to new.c
"""

BINARY_DIFF = """\
diff --git a/data.bin b/data.bin
index abc..def 100644
Binary files a/data.bin and b/data.bin differ
"""

MODE_ONLY_DIFF = """\
diff --git a/script.sh b/script.sh
old mode 100644
new mode 100755
"""


def test_parse_single_file():
    files = _parse_diff_into_files(SIMPLE_DIFF)
    assert "mrc.c" in files
    assert "int margin = 5;" in files["mrc.c"]["added"]
    assert "return;" in files["mrc.c"]["removed"]


def test_parse_two_files():
    files = _parse_diff_into_files(TWO_FILE_DIFF)
    assert "mrc.c" in files
    assert "timing.c" in files


def test_parse_rename_does_not_crash():
    files = _parse_diff_into_files(RENAME_DIFF)
    # rename diffs are parsed; either old or new name captured
    assert len(files) >= 1


def test_parse_binary_does_not_crash():
    files = _parse_diff_into_files(BINARY_DIFF)
    assert "data.bin" in files
    # Binary diffs have no +/- lines — should be empty lists
    assert files["data.bin"]["added"] == []


def test_parse_mode_only_does_not_crash():
    files = _parse_diff_into_files(MODE_ONLY_DIFF)
    assert "script.sh" in files


def test_parse_empty_diff():
    files = _parse_diff_into_files("")
    assert files == {}


# ── _token_similarity ────────────────────────────────────────────────────

def test_similarity_identical():
    lines = ["int x = 1;", "return x;"]
    assert _token_similarity(lines, lines) == 1.0


def test_similarity_empty_both():
    assert _token_similarity([], []) == 1.0


def test_similarity_disjoint():
    a = ["int x = 1;"]
    b = ["void foo() {}"]
    assert _token_similarity(a, b) == 0.0


def test_similarity_partial():
    a = ["int x = 1;", "int y = 2;", "return x;"]
    b = ["int x = 1;", "int z = 9;", "return 0;"]
    score = _token_similarity(a, b)
    assert 0.0 < score < 1.0


def test_similarity_empty_one_side():
    assert _token_similarity(["int x = 1;"], []) == 0.0
    assert _token_similarity([], ["int x = 1;"]) == 0.0


# ── _classify ────────────────────────────────────────────────────────────

def test_classify_match():
    assert _classify(0.75) == "MATCH"
    assert _classify(1.0) == "MATCH"


def test_classify_partial():
    assert _classify(0.40) == "PARTIAL"
    assert _classify(0.74) == "PARTIAL"


def test_classify_mismatch():
    assert _classify(0.0) == "MISMATCH"
    assert _classify(0.39) == "MISMATCH"
