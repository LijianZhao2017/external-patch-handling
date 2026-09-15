"""Tests for config defaults and environment overrides."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "python"))

from config import Config


def test_default_release_is_generic(tmp_path, monkeypatch):
    monkeypatch.delenv("PATCH_PIPELINE_RELEASE", raising=False)
    cfg = Config.load(repo_path=tmp_path)
    assert cfg.release == "release-name"


def test_release_can_be_overridden_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATCH_PIPELINE_RELEASE", "custom-release")
    cfg = Config.load(repo_path=tmp_path)
    assert cfg.release == "custom-release"



def test_test_timeout_can_be_overridden_by_env(tmp_path, monkeypatch):
    monkeypatch.setenv("PATCH_PIPELINE_TEST_TIMEOUT_SECONDS", "45")
    cfg = Config.load(repo_path=tmp_path)
    assert cfg.test_timeout_seconds == 45
