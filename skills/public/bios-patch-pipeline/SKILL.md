---
name: bios-patch-pipeline
description: Use this skill whenever the user wants to receive, validate, review, apply, or triage external BIOS or firmware patch bundles against a git repo. Trigger on requests involving `.patch` series, `git format-patch`, `.7z` or `.zip` archives, review branches, release branches such as `release/bhs_pb2_35d44`, `git am` conflicts, Intel BIOS trees like `~/OKS/Intel`, or when the user asks for a patch review report even if they do not explicitly mention a pipeline.
compatibility: Requires bash, git, and filesystem access. Works best when the target repo is local and the patch input is a directory of `.patch` files or an extractable archive.
---

# BIOS Patch Pipeline

Use this skill to run a safe, manual patch review workflow without depending on the repository's Python or bash pipeline scripts.

The goal is to help the user answer four questions reliably:

1. What exactly is in the patch bundle?
2. What base branch should the review branch come from?
3. Can the patch series apply cleanly?
4. If not, is the failure caused by path-root mismatch, missing ancestor data, or real content drift?

## Inputs to collect

Establish these inputs before acting:

- Patch source: archive path or directory of `.patch` files
- Target repository path
- Intended release or base branch
- Optional staging label/date for the review run

If the user gives a release name like `bhs_pb2_35d44` but not a branch, derive the base branch as `release/<release>`.

If the user gives neither a base branch nor a release, inspect the repo and ask only if you truly cannot infer a safe base.

## Operating principles

- Treat the patch source as read-only. If you need to normalize paths for diagnosis, copy the patches into a temp directory first.
- Prefer creating a local tracking branch from `origin/<branch>` when the base branch does not exist locally.
- Create the review branch as `review/<date>/<slug>` from the chosen base branch.
- Keep the target repo recoverable. If `git am` starts and fails, either leave clear instructions or abort before finishing if the user asked only for diagnosis.
- Leave the repo on a stable branch at the end whenever feasible.
- Do not silently rewrite source patches or integrate changes without telling the user.

## Workflow

### 1. Intake and extraction

If the source is an archive:

- Detect the archive type
- Extract it to a temp directory
- Find the actual directory containing `.patch` files

If the source is already a directory:

- Enumerate `.patch` files in sort order

Fail fast if no `.patch` files exist.

### 2. Patch validation

For each patch, check:

- `From ` or `From:` header near the top
- `Subject:` header
- `diff --git` content

Capture:

- subject
- author
- files touched
- insertions/deletions

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

### 6. Apply strategy

Preferred sequence:

1. Try `git am --3way`
2. If it fails, capture the exact stderr
3. Decide whether the failure is:
   - path-root mismatch
   - ancestor-data failure
   - actual hunk/content conflict

If you need an additional diagnostic pass, use copied patches in a temp area. For example, stripping a leading `Intel/` from copied patch paths can confirm a root mismatch, but this should be reported as diagnosis, not treated as a silent fix.

### 7. Report

Always finish with a concise report using this structure:

## Patch pipeline report

- Source:
- Repo:
- Base branch:
- Review branch:
- Patch count:

### Receive
- Valid patches:
- Skipped patches:
- Notes:

### Preflight findings
- Branch preparation:
- Path-root findings:
- Ancestor-data findings:

### Apply result
- Status: `success` / `blocked`
- First failing patch:
- First failing file:
- Exact failure signature:

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

## Examples

### Example 1: Real BIOS intake

Input:

`Test /mnt/c/temp/GNR_PATCH_v13_change14-15_260320.7z against ~/OKS/Intel using release bhs_pb2_35d44`

Expected behavior:

- extract archive
- derive base branch `release/bhs_pb2_35d44`
- create local tracking branch if needed
- create review branch
- report whether apply is blocked by root mismatch, ancestor failure, or content drift

### Example 2: Directory input

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
