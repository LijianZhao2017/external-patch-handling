"""Tests for base-branch resolution and branch preparation helpers."""

import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest

from config import Config
from utils import GitError, ensure_clean_worktree, ensure_local_branch


def _git(cwd, *args):
    return subprocess.run(
        ["git", "--no-pager", *args],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )


def _init_repo(path):
    _git(path, "init")
    _git(path, "config", "user.name", "Test User")
    _git(path, "config", "user.email", "test@example.com")
    (path / "README").write_text("hello\n")
    _git(path, "add", "README")
    _git(path, "commit", "-m", "init")


def test_resolved_working_branch_defaults_to_main(tmp_path):
    cfg = Config.load(repo_path=tmp_path)
    assert cfg.resolved_working_branch == "main"


def test_resolved_working_branch_prefers_base_branch(tmp_path):
    (tmp_path / ".patch-pipeline.toml").write_text('base_branch = "release/bhs_pb2_35d44"\n')
    cfg = Config.load(repo_path=tmp_path)
    assert cfg.resolved_working_branch == "release/bhs_pb2_35d44"


def test_resolved_working_branch_derives_release_branch(tmp_path):
    (tmp_path / ".patch-pipeline.toml").write_text('release = "bhs_pb2_35d44"\n')
    cfg = Config.load(repo_path=tmp_path)
    assert cfg.resolved_working_branch == "release/bhs_pb2_35d44"


def test_resolved_working_branch_uses_explicit_working_branch(tmp_path):
    (tmp_path / ".patch-pipeline.toml").write_text(
        'release = "bhs_pb2_35d44"\nworking_branch = "cxsh/add-doe9-32gb-support-pb2"\n'
    )
    cfg = Config.load(repo_path=tmp_path)
    assert cfg.resolved_working_branch == "cxsh/add-doe9-32gb-support-pb2"


def test_ensure_clean_worktree_ignores_staging_dir(tmp_path):
    _init_repo(tmp_path)
    staging = tmp_path / ".patch-staging" / "2026-03-27"
    staging.mkdir(parents=True)
    (staging / "review_data.json").write_text("{}")

    ensure_clean_worktree(tmp_path, ignored_paths=[".patch-staging/"])


def test_ensure_clean_worktree_rejects_other_untracked_files(tmp_path):
    _init_repo(tmp_path)
    (tmp_path / "notes.txt").write_text("todo\n")

    with pytest.raises(GitError):
        ensure_clean_worktree(tmp_path, ignored_paths=[".patch-staging/"])


def test_ensure_local_branch_creates_tracking_branch(tmp_path):
    _init_repo(tmp_path)
    _git(tmp_path, "remote", "add", "origin", "https://example.invalid/repo.git")
    head = _git(tmp_path, "rev-parse", "HEAD").stdout.strip()
    _git(tmp_path, "update-ref", "refs/remotes/origin/release/bhs_pb2_35d44", head)

    created = ensure_local_branch(tmp_path, "release/bhs_pb2_35d44")

    assert created is True
    branch = _git(tmp_path, "rev-parse", "--verify", "refs/heads/release/bhs_pb2_35d44").stdout.strip()
    assert branch == head
    upstream = _git(tmp_path, "rev-parse", "--symbolic-full-name", "release/bhs_pb2_35d44@{upstream}").stdout.strip()
    assert upstream == "refs/remotes/origin/release/bhs_pb2_35d44"
