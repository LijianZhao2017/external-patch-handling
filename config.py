"""
Patch Pipeline — Shared Configuration

Loads settings from (in priority order):
  1. Environment variables (PATCH_PIPELINE_*)
  2. .patch-pipeline.toml in the repo root
  3. Built-in defaults
"""

from __future__ import annotations

import os
import sys

if sys.version_info < (3, 11):
    raise SystemExit("patch-pipeline requires Python 3.11+ (for tomllib). "
                     "Upgrade Python or install 'tomli' as a fallback.")
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Config:
    # Paths
    repo_path: Path = Path(".")
    sharepoint_base: str = ""  # local mount point, e.g. /mnt/sharepoint/patches
    staging_dir: str = ".patch-staging"

    # Branch names
    working_branch: str = "main"
    base_branch: str = ""
    review_branch_prefix: str = "review"

    # Shared folder convention: <release>/<date>/
    release: str = "release-name"

    # Build & test commands (empty = skip)
    build_command: str = ""
    unit_test_command: str = ""

    # Limits
    max_patch_size_kb: int = 500
    allowed_path_prefixes: list[str] = field(default_factory=list)

    @classmethod
    def load(cls, repo_path: Path | str | None = None) -> "Config":
        """Load config from toml file + env overrides."""
        cfg = cls()

        if repo_path:
            cfg.repo_path = Path(repo_path).resolve()
        else:
            cfg.repo_path = Path.cwd()

        # Try loading .patch-pipeline.toml
        toml_path = cfg.repo_path / ".patch-pipeline.toml"
        if toml_path.exists():
            with open(toml_path, "rb") as f:
                data = tomllib.load(f)
            for key, val in data.items():
                if hasattr(cfg, key):
                    if key == "repo_path":
                        setattr(cfg, key, Path(val).resolve())
                    elif key == "allowed_path_prefixes":
                        setattr(cfg, key, list(val))
                    else:
                        setattr(cfg, key, val)

        # Environment variable overrides (PATCH_PIPELINE_<FIELD>)
        for fld in cfg.__dataclass_fields__:
            env_key = f"PATCH_PIPELINE_{fld.upper()}"
            env_val = os.environ.get(env_key)
            if env_val is not None:
                if fld == "repo_path":
                    cfg.repo_path = Path(env_val).resolve()
                elif fld == "max_patch_size_kb":
                    cfg.max_patch_size_kb = int(env_val)
                elif fld == "allowed_path_prefixes":
                    cfg.allowed_path_prefixes = [p.strip() for p in env_val.split(",") if p.strip()]
                else:
                    setattr(cfg, fld, env_val)

        return cfg

    @property
    def staging_path(self) -> Path:
        return self.repo_path / self.staging_dir

    @property
    def resolved_working_branch(self) -> str:
        if self.base_branch:
            return self.base_branch
        if self.working_branch != "main":
            return self.working_branch
        if self.release and self.release != "release-name":
            return f"release/{self.release}"
        return self.working_branch
