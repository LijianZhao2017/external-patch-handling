---
name: bios-patch-pipeline
description: Use this skill whenever the user wants to receive, validate, review, apply, or triage external BIOS or firmware patch bundles against a git repo. Trigger on requests involving `.patch` series, `git format-patch`, `.7z` or `.zip` archives, review branches, release branches such as `release/bhs_pb2_35d44`, `git am` conflicts, Intel BIOS trees like `~/OKS/Intel`, or when the user asks for a patch review report even if they do not explicitly mention a pipeline. Also trigger when the user mentions CRLF patch failures, vendor markers like `//CXSH+`, patch line-ending issues, or cross-platform patch application problems.
compatibility: Requires bash, git, and filesystem access. Works best when the target repo is local and the patch input is a directory of `.patch` files or an extractable archive.
---

# BIOS Patch Pipeline

Use this skill to run a safe, manual patch review workflow without depending on the repository's Python or bash pipeline scripts.

The goal is to help the user answer five questions reliably:

1. What exactly is in the patch bundle?
2. What base branch should the review branch come from?
3. Can the patch series apply cleanly?
4. If not, is the failure caused by CRLF line endings, path-root mismatch, missing ancestor data, or real content drift?
5. Does the applied code match the codebase's style and conventions?

## Inputs to collect

Establish these inputs before acting:

- Patch source: archive path or directory of `.patch` files
- Target repository path
- Intended release or base branch
- Optional staging label/date for the review run
- Optional design document references (PDF/doc paths for review checklist)

If the user gives a release name like `bhs_pb2_35d44` but not a branch, derive the base branch as `release/<release>`.

If the user gives neither a base branch nor a release, inspect the repo and ask only if you truly cannot infer a safe base.

## Operating principles

- Treat the patch source as read-only. If you need to normalize paths or line endings, copy the patches into a temp directory first.
- Prefer creating a local tracking branch from `origin/<branch>` when the base branch does not exist locally.
- Create the review branch as `review/<date>/<slug>` from the chosen base branch.
- Keep the target repo recoverable. If `git am` starts and fails, abort cleanly before retrying with a different strategy.
- Leave the repo on a stable branch at the end whenever feasible.
- Do not silently rewrite source patches or integrate changes without telling the user.
- When editing files that have CRLF line endings, always use binary-safe reads/writes (`read_bytes()`/`write_bytes()`) to avoid Python's universal newline mode silently converting CRLF→LF across entire files.

## Workflow

### 1. Intake and extraction

If the source is an archive:

- Detect the archive type
- Extract it to a temp directory
- Find the actual directory containing `.patch` files

If the source is already a directory:

- Enumerate `.patch` files in sort order

Fail fast if no `.patch` files exist.

### 2. Patch validation and preparation

For each patch, check:

- `From ` or `From:` header near the top
- `Subject:` header
- `diff --git` content

Capture:

- subject, author, date, commit body (text between `Subject:` continuation and `---` separator)
- files touched
- insertions/deletions

**CRLF detection:** Check each patch file for CRLF line endings (`\r\n`). This is the most common cause of `git am` failure on cross-platform patches — context lines won't match when the patch has CRLF but the repo has LF (or vice versa). If detected:

- Report the finding clearly before attempting apply
- Create a normalized copy with binary `b"\r\n"` → `b"\n"` replacement (no text-mode decode — preserves non-ASCII author names)
- Use the normalized copy for apply attempts

**Vendor marker detection:** Scan added lines (lines starting with `+` in diff hunks, not commit messages) for vendor-specific annotations like `//CXSH+`, `//CXSH-`, `//VENDOR+`, etc. Common patterns: `//\w+\+\s*$` and `//\w+-\s*$`. Report any findings — these are change delimiters used by external vendors but not present in Intel codebases. They should be removed post-apply.

Summarize the bundle before modifying the repo.

### 3. Base branch resolution

Resolve the base branch in this order:

1. User-specified base branch
2. `release/<release>` derived from a release name
3. Existing repo/project convention if clearly documented
4. Current branch only as a last resort, and only if that fallback is explained

Before checkout:

- verify whether `refs/heads/<branch>` exists
- if not, check `refs/remotes/origin/<branch>`
- if only the remote exists, create a local tracking branch

### 4. Preflight diagnostics before apply

Run preflight checks before `git am`:

- ensure the worktree is clean enough for review work
- inspect whether patch file paths line up with the repo root
- optionally run `git apply --check` on a copied patch to get a fast failure signature

Pay special attention to root-prefix mismatch:

- If the repo root already ends with `Intel`
- and the patch paths begin with `Intel/...`
- then the patch likely came from one level higher in the tree

Call this out explicitly as a path-root mismatch. This is often different from a real content conflict.

Also distinguish 3-way ancestor failures:

- `sha1 information is lacking or useless`
- `could not build fake ancestor`

These usually mean the patch's blob ancestry is unavailable or unusable in the target repo, even before considering content drift.

### 5. Review branch creation

Create the review branch as:

`review/<date>/<slug>`

The slug should come from the first patch subject, normalized to lowercase with hyphens.

Print the chosen base branch and review branch before applying.

### 6. Apply strategy — strict-then-fallback

This is the most critical step. External vendor patches frequently fail on first attempt due to CRLF, missing ancestry, or path mismatches. Use a cascading strategy:

**Attempt 1: Strict apply**
1. Try `git am --3way` with prepared (normalized) patch
2. If it succeeds, record `apply_method: "git-am"`, `whitespace_relaxed: false`

**Attempt 2: Whitespace-relaxed apply** (if attempt 1 fails)
1. Run `git am --abort` to clean up the failed state
2. Verify worktree is clean (`git status --porcelain` shows no changes)
3. Try `git am --3way --ignore-whitespace` with prepared patch
4. If it succeeds, record `apply_method: "git-am"`, `whitespace_relaxed: true`

**Attempt 3: Manual apply fallback** (if attempt 2 also fails)
1. Run `git am --abort` to clean up
2. Verify worktree is clean
3. Try `git apply --ignore-whitespace <patch>`
4. If it applies, create a commit preserving original metadata:
   - Author name/email from patch header
   - Author date from patch header
   - Subject and body from patch header
   ```bash
   git commit --author="Name <email>" --date="date" -m "subject

   body"
   ```
5. Record `apply_method: "git-apply-fallback"`, `whitespace_relaxed: true`

**If all attempts fail:**
- Capture and report the exact stderr from each attempt
- Classify the failure (path-root mismatch, ancestor-data failure, or content drift)
- Leave clear instructions for manual resolution

Important: always run `git am --abort` between attempts. Without it, `.git/rebase-apply/` persists and the next `git am` will fail with "previous rebase directory still exists."

### 7. Post-apply cleanup

After successful apply, check for issues in the applied code:

**Vendor marker removal:** If vendor markers were detected in step 2, check whether they landed in the committed code. If so, remove them using binary-safe file operations (`read_bytes()`/`write_bytes()`) to preserve existing line endings, then create a fixup commit.

**Style spot-check:** On the lines introduced by the patch (the `+` lines from `git diff base..review`), check for:
- Trailing whitespace (spaces/tabs before line ending)
- Inconsistent line endings within a file (mixed CRLF/LF)
- Indentation mismatches with surrounding code

Report any findings. These are advisory — they don't block the pipeline but should be fixed before merge.

### 8. Report

Always finish with a concise report using this structure:

## Patch pipeline report

- Source:
- Repo:
- Base branch:
- Review branch:
- Patch count:
- Design documents: (if provided)

### Receive
- Valid patches:
- Skipped patches:
- CRLF detected: yes/no (normalized: yes/no)
- Vendor markers detected: count and files
- Notes:

### Preflight findings
- Branch preparation:
- Path-root findings:
- Ancestor-data findings:

### Apply result
- Status: `success` / `blocked`
- Apply method: `git-am` / `git-am --ignore-whitespace` / `git-apply-fallback`
- First failing patch: (if blocked)
- First failing file: (if blocked)
- Exact failure signature: (if blocked)

### Post-apply cleanup
- Vendor markers removed: count (if any)
- Style warnings: count and summary (if any)

### Next actions
- Action 1
- Action 2
- Action 3

If a generated report file exists, include its path too.

## Failure interpretation guide

Use these meanings consistently:

- `No .patch files found` → wrong input path or archive extraction path
- `Missing 'From' header` or `Missing 'Subject:'` → not a real `format-patch` series
- `sha1 information is lacking or useless` → patch ancestry cannot support 3-way apply
- `could not build fake ancestor` → same family as above; do not describe it as a normal merge conflict
- `patch does not apply` → content drift or wrong root after plain-context apply
- paths starting with `Intel/` against repo `.../Intel` → likely one-directory root mismatch
- `\r\n` / CRLF in patch file → cross-platform line ending mismatch; normalize patch to LF first
- `//VENDOR+` / `//VENDOR-` markers in diff hunks → vendor-specific change annotations to be removed post-apply

## CRLF handling — lessons learned

Windows-authored patches commonly have CRLF (`\r\n`) line endings. This causes `git am` to fail because context lines don't match the working tree. The correct approach:

1. **Detect** CRLF in the patch file before attempting apply
2. **Normalize** by copying the patch and doing binary `b"\r\n"` → `b"\n"` replacement (never use Python `read_text()` — it silently converts CRLF→LF on the entire file via universal newline mode)
3. **Apply** the normalized copy with the strict-then-fallback strategy
4. **Preserve** the original patch file untouched for audit

When editing files in a CRLF codebase after apply, always use `read_bytes()`/`write_bytes()` for surgical changes. Using `read_text()`/`write_text()` will silently convert the entire file from CRLF to LF, creating a massive diff of every line.

## Examples

### Example 1: CRLF vendor patch (most common real-world case)

Input:

`Integrate the CXSH EMR.patch to ~/OKS/Intel, target branch family/server2`

Expected behavior:

- find the patch file, validate format
- detect CRLF line endings, create normalized copy
- detect `//CXSH+`/`//CXSH-` vendor markers, report them
- create local tracking branch for `family/server2`
- create review branch `review/<date>/<slug>`
- attempt strict `git am` → likely fails (CRLF + missing ancestry)
- fallback to `git apply --ignore-whitespace` with normalized patch
- commit preserving original author metadata
- remove vendor markers from applied code via fixup commit
- report results including apply method and cleanup actions

### Example 2: Archive input

Input:

`Test /mnt/c/temp/GNR_PATCH_v13_change14-15_260320.7z against ~/OKS/Intel using release bhs_pb2_35d44`

Expected behavior:

- extract archive
- derive base branch `release/bhs_pb2_35d44`
- create local tracking branch if needed
- create review branch
- report whether apply is blocked by root mismatch, ancestor failure, or content drift

### Example 3: Directory input

Input:

`Review these format-patch files in ~/incoming/fixset-42 against ~/work/openbmc on release/2.18`

Expected behavior:

- validate the series
- prepare the release base branch
- attempt apply on a review branch
- summarize results and next actions

## When not to use this skill

Do not use this skill for:

- ad hoc single-file diffs that are not `format-patch`
- already-integrated branches where the user wants a normal code review
- generic git tutoring unrelated to patch intake/apply/report workflows
