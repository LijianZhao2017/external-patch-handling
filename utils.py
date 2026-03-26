"""
Patch Pipeline — Utility helpers

Git subprocess wrapper, worktree checks, patch file discovery, formatting.
"""

from __future__ import annotations

import logging
import re
import subprocess
from datetime import datetime
from pathlib import Path

logger = logging.getLogger("patch-pipeline")


class GitError(Exception):
    """Raised when a git command fails."""


def git_run(
    *args: str,
    cwd: Path | str | None = None,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess:
    """Run a git command and return the result."""
    cmd = ["git", "--no-pager"] + list(args)
    logger.debug("Running: %s", " ".join(cmd))
    result = subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
        timeout=120,
    )
    if check and result.returncode != 0:
        stderr = result.stderr.strip() if result.stderr else ""
        raise GitError(f"git {args[0]} failed (rc={result.returncode}): {stderr}")
    return result


def ensure_clean_worktree(repo: Path) -> None:
    """Abort if there are uncommitted changes."""
    result = git_run("status", "--porcelain", cwd=repo)
    if result.stdout.strip():
        raise GitError(
            "Working tree is not clean. Commit or stash changes first.\n"
            + result.stdout.strip()
        )


def list_patches(directory: Path) -> list[Path]:
    """Find .patch files in a directory, sorted by name (number prefix)."""
    patches = sorted(directory.glob("*.patch"), key=lambda p: p.name)
    return patches


def validate_format_patch(path: Path) -> tuple[bool, str]:
    """Check if a file looks like valid git format-patch output.

    Returns (is_valid, reason).
    """
    try:
        content = path.read_text(errors="replace")
    except OSError as e:
        return False, f"Cannot read file: {e}"

    lines = content.split("\n", 50)  # only need first ~50 lines
    has_from = any(line.startswith("From ") or line.startswith("From:") for line in lines[:10])
    has_subject = any(line.startswith("Subject:") for line in lines[:20])
    has_diff = "diff --git" in content

    if not has_from:
        return False, "Missing 'From' header — not a git format-patch file"
    if not has_subject:
        return False, "Missing 'Subject:' header"
    if not has_diff:
        return False, "Missing 'diff --git' — no actual diff content"

    return True, "OK"


def parse_patch_header(path: Path) -> dict:
    """Extract subject, author, date, and affected files from a patch."""
    content = path.read_text(errors="replace")
    info: dict = {"file": path.name, "subject": "", "author": "", "date": "", "files": []}

    for line in content.split("\n", 60):
        if line.startswith("Subject:"):
            # Strip [PATCH N/M] prefix
            subj = re.sub(r"\[PATCH[^\]]*\]\s*", "", line[len("Subject:"):].strip())
            info["subject"] = subj
        elif line.startswith("From:"):
            info["author"] = line[len("From:"):].strip()
        elif line.startswith("Date:"):
            info["date"] = line[len("Date:"):].strip()

    # Extract affected files from diff --git lines
    files = re.findall(r"diff --git a/(.+?) b/", content)
    info["files"] = sorted(set(files))

    # Count insertions/deletions from the stat line (last --- line before diffs)
    stat_match = re.search(
        r"(\d+) files? changed(?:, (\d+) insertions?\(\+\))?(?:, (\d+) deletions?\(-\))?",
        content,
    )
    if stat_match:
        info["files_changed"] = int(stat_match.group(1))
        info["insertions"] = int(stat_match.group(2) or 0)
        info["deletions"] = int(stat_match.group(3) or 0)
    else:
        info["files_changed"] = len(info["files"])
        info["insertions"] = 0
        info["deletions"] = 0

    return info


def slugify(text: str, max_len: int = 50) -> str:
    """Convert text to a branch-name-safe slug."""
    slug = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return (slug or "unnamed")[:max_len]


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def format_table(headers: list[str], rows: list[list[str]]) -> str:
    """Format a simple markdown table."""
    widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))

    lines = []
    header_line = "| " + " | ".join(h.ljust(w) for h, w in zip(headers, widths)) + " |"
    sep_line = "| " + " | ".join("-" * w for w in widths) + " |"
    lines.append(header_line)
    lines.append(sep_line)
    for row in rows:
        line = "| " + " | ".join(
            (row[i] if i < len(row) else "").ljust(widths[i])
            for i in range(len(headers))
        ) + " |"
        lines.append(line)
    return "\n".join(lines)
