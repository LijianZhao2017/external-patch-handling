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


def _status_path(line: str) -> str:
    path = line[3:].strip()
    if path.startswith('"') and path.endswith('"'):
        path = path[1:-1]
    if " -> " in path:
        path = path.split(" -> ", 1)[1].strip()
    return path


def ensure_clean_worktree(repo: Path, ignored_paths: list[str] | None = None) -> None:
    """Abort if there are uncommitted changes outside ignored paths."""
    ignored = tuple((ignored_paths or []))
    result = git_run("status", "--porcelain", "--untracked-files=all", cwd=repo)
    dirty_lines = []
    for line in result.stdout.splitlines():
        path = _status_path(line)
        if any(path == item.rstrip("/") or path.startswith(item.rstrip("/") + "/") for item in ignored):
            continue
        dirty_lines.append(line)

    if dirty_lines:
        raise GitError(
            "Working tree is not clean. Commit or stash changes first.\n"
            + "\n".join(dirty_lines)
        )


def ensure_local_branch(repo: Path, branch: str, remote: str = "origin") -> bool:
    """Create a local tracking branch if only the remote branch exists.

    Also handles tags — if ``branch`` names a tag, returns False so the caller
    can proceed directly to ``git checkout <tag>`` (detached HEAD is fine for
    creating a new review branch on top of it).
    """
    local_ref = f"refs/heads/{branch}"
    remote_ref = f"refs/remotes/{remote}/{branch}"
    tag_ref = f"refs/tags/{branch}"

    if git_run("rev-parse", "--verify", local_ref, cwd=repo, check=False).returncode == 0:
        return False

    if git_run("rev-parse", "--verify", remote_ref, cwd=repo, check=False).returncode == 0:
        git_run("branch", "--track", branch, f"{remote}/{branch}", cwd=repo)
        return True

    if git_run("rev-parse", "--verify", tag_ref, cwd=repo, check=False).returncode == 0:
        return False  # it's a tag; git checkout <tag> will work fine

    raise GitError(
        f"Base branch '{branch}' not found locally, as {remote}/{branch}, or as a tag."
    )


def detect_patch_root_prefix(files: list[str], repo: Path) -> str | None:
    """Detect when patch paths redundantly include the repo root name.

    Handles both single-level (``MemoryFirmware/foo.c``) and multi-level
    prefixes (``OakStream/.../MemoryFirmware/foo.c``) — any path where the
    repo directory name appears as a component followed by the actual file path.

    Returns the common prefix string (without trailing slash) when:
      - Every file shares the same prefix that ends with ``/<repo-name>``
        (or ``<repo-name>`` at path start)
      - At least one stripped path exists in the repo (confirming the mapping)
      - No file's full (unstripped) path exists in the repo

    Returns ``None`` if the criteria are not met — partial prefix detection
    would be unreliable.

    Examples:
      repo path: /work/Intel
      patch file: Intel/ServerSiliconPkg/foo.c   → prefix "Intel"

      repo path: ~/OKS/MemoryFirmware
      patch file: OakStream/sub/MemoryFirmware/ServerMemoryPkg/foo.c
                                                → prefix "OakStream/sub/MemoryFirmware"
    """
    if not files:
        return None

    repo_name = repo.name

    def _extract_prefix(file_path: str) -> str | None:
        # Case 1: path starts directly with repo_name/
        if file_path.startswith(repo_name + "/"):
            return repo_name
        # Case 2: repo_name appears as a component later in the path
        marker = "/" + repo_name + "/"
        idx = file_path.find(marker)
        if idx != -1:
            return file_path[: idx + 1 + len(repo_name)]
        return None

    common_prefix: str | None = None
    for file_path in files:
        p = _extract_prefix(file_path)
        if p is None:
            return None
        if common_prefix is None:
            common_prefix = p
        elif common_prefix != p:
            return None  # inconsistent prefixes across files

    if common_prefix is None:
        return None

    # Confirm: at least one file's stripped path exists, none of the full paths do
    confirmed = False
    for file_path in files:
        if (repo / file_path).exists():
            # Full path exists → no stripping needed
            return None
        stripped = file_path[len(common_prefix) + 1:]
        if (repo / stripped).exists():
            confirmed = True

    return common_prefix if confirmed else None


def rewrite_patch_with_stripped_prefix(text: str, prefix: str) -> str:
    """Rewrite a patch text to strip a leading path prefix from diff headers.

    Only rewrites lines that are actual diff headers (``diff --git``,
    ``---``, ``+++``) so that commit message bodies are not mangled.
    """
    out_lines: list[str] = []
    for line in text.splitlines(True):
        if line.startswith(f"diff --git a/{prefix}/"):
            line = line.replace(f"a/{prefix}/", "a/", 1).replace(f"b/{prefix}/", "b/", 1)
        elif line.startswith(f"--- a/{prefix}/"):
            line = line.replace(f"a/{prefix}/", "a/", 1)
        elif line.startswith(f"+++ b/{prefix}/"):
            line = line.replace(f"b/{prefix}/", "b/", 1)
        out_lines.append(line)
    return "".join(out_lines)


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
