# Patch Review Pipeline

[中文文档](README_CN.md)

> **Requirements:** Python 3.11+, git (receiver side only)

```bash
python -m pip install -r requirements-dev.txt
```

Configure by creating `.patch-pipeline.toml` in the repo root:

```toml
release = "bhs_pb2_35d44"
base_branch = "release/bhs_pb2_35d44"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
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
│   └── patch_integrate.py
├── bash/                      # Bash implementation (zero dependencies)
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
python python/patch_receive.py /mnt/shared-patches/release-name/2026-03-26/
# Bash
bash bash/patch_receive.sh /mnt/shared-patches/release-name/2026-03-26/
```

Validates each `.patch` file (must be `git format-patch` output), shows diff stats, runs static checks, stages patches locally.

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
- **EXTRA** — Receiver has changes in a file sender didn't touch (adaptation)

### Step 4 — Run Tests

```bash
python python/patch_test.py
# or: bash bash/patch_test.sh
```

Runs build + unit tests automatically. Prompts for silicon test results (PASS/FAIL/PENDING).

### Step 5 — Generate Report & Integrate

```bash
python python/patch_report.py     # creates REVIEW_REPORT.md
python python/patch_integrate.py  # after sender says LGTM
# or: bash bash/patch_integrate.sh
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `git am` conflict | Fix files, `git add`, `git am --continue`. Or `git am --abort`. |
| Cherry-pick conflict | Fix files, `git add`, `git cherry-pick --continue`. Or `--abort`. |
| MISMATCH in check | Review side-by-side output. Confirm with sender if functionally equivalent. |
| MISSING file | Check `git am` log and re-apply manually if needed. |
| EXTRA files | Usually fine — receiver adapted context lines. Verify no unintended changes. |

## Running Tests

```bash
python -m pytest tests/ -v
```
