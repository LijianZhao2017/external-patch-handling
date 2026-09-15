"""Tests for noninteractive receive and forced-session cleanup."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "python"))

from config import Config
from patch_receive import receive_patches


PATCH = """From 1111111111111111111111111111111111111111 Mon Sep 17 00:00:00 2001
From: Test User <test@example.com>
Date: Tue, 15 Sep 2026 15:00:00 +0800
Subject: [PATCH] replace staged patch

---
 file.txt | 1 +
 1 file changed, 1 insertion(+)

diff --git a/file.txt b/file.txt
index e69de29..257cc56 100644
--- a/file.txt
+++ b/file.txt
@@ -0,0 +1 @@
+new
--
2.40.0
"""


def test_force_replaces_stale_session_without_prompt(tmp_path):
    source = tmp_path / "source"
    source.mkdir()
    (source / "0001-replace.patch").write_text(PATCH)
    cfg = Config.load(repo_path=tmp_path)
    staging = cfg.staging_path / "2026-09-15"
    staging.mkdir(parents=True)
    (staging / "0001-stale.patch").write_text("stale")
    (staging / "old.json").write_text("old")

    result = receive_patches(
        source,
        cfg,
        date="2026-09-15",
        force=True,
        prompt_notes=False,
    )

    assert [item["subject"] for item in result] == ["replace staged patch"]
    assert not (staging / "0001-stale.patch").exists()
    assert not (staging / "old.json").exists()
    assert (staging / "0001-replace.patch").exists()
