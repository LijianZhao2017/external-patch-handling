# Patch Review Pipeline

[中文文档](README_CN.md)

> **Requirements:** Python 3.10+ (3.11+ recommended — uses built-in `tomllib`; on 3.10 install the `tomli` backport), git (receiver side only)

```bash
python -m pip install -r requirements-dev.txt
```

Configure by creating `.patch-pipeline.toml` in the repo root:

```toml
release = "bhs_pb2_35d44"
base_branch = "release/bhs_pb2_35d44"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
test_timeout_seconds = 600
```

Or use environment variables: `PATCH_PIPELINE_RELEASE=release-name`, `PATCH_PIPELINE_BASE_BRANCH=...`, etc.

---

## Repository Layout

```
repo-root/
├── python/                    # Python implementation
│   ├── config.py
│   ├── utils.py
│   ├── patch_receive.py
│   ├── patch_apply.py
│   ├── patch_check.py
│   ├── patch_test.py
│   ├── patch_report.py
│   ├── patch_integrate.py
│   └── approval.py
├── bash/                      # Bash orchestration (uses Python for JSON metadata)
│   ├── patch_receive.sh
│   ├── patch_apply.sh
│   ├── patch_check.sh
│   ├── patch_test.sh
│   └── patch_integrate.sh
├── tests/
├── pyproject.toml
├── requirements-dev.txt
└── .patch-pipeline.toml       # config (optional)
```

---

## The 5 Steps

### Step 1 — Receive & Validate Patches

```bash
# Python
python python/patch_receive.py /mnt/shared-patches/release-name/2026-03-26/ --no-prompt
# Bash
bash bash/patch_receive.sh /mnt/shared-patches/release-name/2026-03-26/
```

Validates each `.patch` file (must be `git format-patch` output), shows diff stats, runs static checks, and stages patches locally. Use `--force` only to replace the complete existing date session; it removes stale staged artifacts first. Use `--note "..."` when a skill needs to attach one reviewer note without opening a prompt.

### Step 2 — Apply to Review Branch

```bash
python python/patch_apply.py
# or: bash bash/patch_apply.sh
```

Creates `review/2026-03-26/<patch-slug>` from the configured base branch and applies patches with `git am --3way`. Pauses on conflict for manual resolution.

### Step 3 — Functional Equivalence Check ⭐

```bash
python python/patch_check.py
# or: bash bash/patch_check.sh
```

Compares what the sender *intended* (their patch) vs what *actually landed* on the receiver side. Because codebases diverge through refactoring, this tool checks the same logical changes are present per file.

- **MATCH** (≥75%) — Same logical change landed correctly
- **PARTIAL** (40–75%) — Change partially present; review side-by-side diff
- **MISMATCH** (<40%) — Significant divergence; confirm intent with sender
- **MISSING** — Sender touched this file but nothing landed
- **EXTRA** — Receiver has changes in a file sender didn't touch (requires review; it is not an automatic pass)

Integration requires every result to be `MATCH`; `PARTIAL`, `MISMATCH`, `MISSING`, and `EXTRA` produce `NEEDS REVIEW`.

### Step 4 — Run Tests

```bash
python python/patch_test.py --no-prompt --silicon-result PENDING
# or: bash bash/patch_test.sh --no-prompt --silicon-result PENDING
```

Runs build + unit tests automatically. `--no-prompt` makes skill/CI execution deterministic; provide `--silicon-result PASS|FAIL|PENDING|SKIP` when a hardware result is available.

### Step 5 — Generate Report & Integrate

```bash
python python/patch_report.py     # creates REVIEW_REPORT.md and REVIEW_REPORT.html
python python/patch_integrate.py --approval-file /path/to/approval.json
# or: bash bash/patch_integrate.sh --approval-file /path/to/approval.json
```

Integration is noninteractive and fail-closed. It requires a complete apply, `check_data.json` with every file `MATCH` and no `EXTRA`, `test_data.json` with no `FAIL`/`TIMEOUT`/`ERROR`, and an approval JSON record tied to the exact review branch commit set and report SHA-256. `PENDING`/`SKIPPED` results remain visible; the scoped approval owner decides whether they are acceptable. The integration step includes every commit unique to the review branch, including post-apply cleanup or conflict-resolution commits, then pushes an `integrate/<date>/<slug>` branch and opens a GitHub PR via `gh`. If `gh` is not installed, it prints the equivalent command.

An approval email is acceptable as the human approval source only when the skill exports its immutable message metadata into this JSON shape (do not use a bare `LGTM` or an unscoped yes/no):

```json
{
  "decision": "APPROVED",
  "approval_type": "email",
  "message_id": "<mail-message-id>",
  "sender": "sender@example.com",
  "approved_at": "2026-09-15T15:00:00+08:00",
  "review_branch": "review/2026-03-26/fix-timing",
  "commit_shas": ["<full-review-commit-sha>"],
  "report_file": "REVIEW_REPORT.html",
  "report_sha256": "<64-hex-sha256>"
}
```

The validator stores the verified record as `.patch-staging/<date>/approval_data.json` and includes the approval sender/message ID in the PR body.

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `git am` conflict | Fix files, `git add`, `git am --continue`. Or `git am --abort`. |
| Cherry-pick conflict | Fix files, `git add`, `git cherry-pick --continue`. Or `--abort`. |
| `gh pr create` failed | Ensure `gh auth login` is done. Or run the printed fallback command manually. |
| MISMATCH in check | Review side-by-side output. Confirm with sender if functionally equivalent. |
| MISSING file | Check `git am` log and re-apply manually if needed. |
| EXTRA files | Requires review; receiver changed files not present in the sender patch. |
| Integration blocked | Inspect `approval.py` output; all technical evidence and exact approval scope must match. |
| Stale patches after `--force` | `--force` now replaces the complete date session; re-run receive and apply. |

## Running Tests

```bash
python -m pytest tests/ -v
```
