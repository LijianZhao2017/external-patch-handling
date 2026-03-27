"""Tests for patch path-root handling helpers."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from utils import detect_patch_root_prefix, rewrite_patch_with_stripped_prefix


PATCH_TEXT = """\
diff --git a/Intel/ServerSiliconPkg/Mem/Library/MemDdrioIpLib/Common/MemProjectDdrioCommon.c b/Intel/ServerSiliconPkg/Mem/Library/MemDdrioIpLib/Common/MemProjectDdrioCommon.c
index abc..def 100644
--- a/Intel/ServerSiliconPkg/Mem/Library/MemDdrioIpLib/Common/MemProjectDdrioCommon.c
+++ b/Intel/ServerSiliconPkg/Mem/Library/MemDdrioIpLib/Common/MemProjectDdrioCommon.c
@@ -1,1 +1,2 @@
+foo
"""


def test_detect_patch_root_prefix_for_repo_duplicated_root(tmp_path):
    repo = tmp_path / "Intel"
    target = repo / "ServerSiliconPkg" / "Mem" / "Library" / "MemDdrioIpLib" / "Common"
    target.mkdir(parents=True)
    (target / "MemProjectDdrioCommon.c").write_text("x\n")

    files = [
        "Intel/ServerSiliconPkg/Mem/Library/MemDdrioIpLib/Common/MemProjectDdrioCommon.c"
    ]

    assert detect_patch_root_prefix(files, repo) == "Intel"


def test_detect_patch_root_prefix_returns_none_without_matching_files(tmp_path):
    repo = tmp_path / "Intel"
    repo.mkdir()

    files = ["Intel/ServerSiliconPkg/Mem/Library/MemDdrioIpLib/Common/MemProjectDdrioCommon.c"]

    assert detect_patch_root_prefix(files, repo) is None


def test_rewrite_patch_with_stripped_prefix():
    rewritten = rewrite_patch_with_stripped_prefix(PATCH_TEXT, "Intel")

    assert "diff --git a/ServerSiliconPkg/" in rewritten
    assert "--- a/ServerSiliconPkg/" in rewritten
    assert "+++ b/ServerSiliconPkg/" in rewritten
    assert "diff --git a/Intel/" not in rewritten
