# Patch Review Pipeline — One-Page Process Guide

## Quick Start

> **Requirements:** Python 3.11+, git (receiver side only)

Install unit test tooling:

```bash
python -m pip install -r requirements-dev.txt
```

Configure your repo by creating `.patch-pipeline.toml` in the repo root:

```toml
release = "release-name"
working_branch = "main"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
```

Or use environment variables: `PATCH_PIPELINE_RELEASE=release-name`, etc.

---

## The 5 Steps

### Step 1 — Receive & Review Patches
```bash
python patch_receive.py /mnt/shared-patches/release-name/2026-03-26/
```
Validates each `.patch` file (must be `git format-patch` output), shows diff stats and affected files, runs static checks, stages patches locally.

### Step 2 — Apply to Review Branch
```bash
python patch_apply.py
```
Creates `review/2026-03-26/<patch-slug>` branch and applies patches with `git am --3way`. Pauses on conflict for manual resolution.

### Step 3 — Functional Equivalence Check ⭐
```bash
python patch_check.py
```
**Key step.** Compares what the sender *intended* (their patch) vs what *actually landed* on the receiver side (`git diff main..review-branch`). Because codebases diverge through refactoring, the line numbers and context differ — this tool checks that the same logical changes (added/removed content per file) are present.

- **MATCH** (≥75% similarity) — Same logical change landed correctly
- **PARTIAL** (40–75%) — Change partially present; review the side-by-side diff
- **MISMATCH** (<40%) — Significant divergence; confirm intent with sender
- **MISSING** — Sender touched this file but nothing landed on receiver side
- **EXTRA** — Receiver has changes in a file sender didn't touch (adaptation)

### Step 4 — Run Tests
```bash
python patch_test.py
```
Runs build check + unit tests automatically. Prompts for silicon test results (PASS/FAIL/PENDING).

### Step 5 — Generate Report & Integrate
```bash
python patch_report.py          # creates REVIEW_REPORT.md
# → Upload report to the shared folder, send to sender for blessing
python patch_integrate.py       # after sender says LGTM
```
Report includes: patches table, equivalence check results, test results, LGTM checkbox. Integration cherry-picks from review branch to working branch after confirming sender blessing.

---

## Flow Diagram

```
SENDER                        SHARED FOLDER                   RECEIVER
──────                        ──────────                      ────────
git format-patch           →  /release-name/2026-03-26/   ←  1. patch_receive.py
                                   *.patch                         │
                                                             2. patch_apply.py
                                                               (review/<date>/... branch)
                                                                  │
                                                             3. patch_check.py ⭐
                                                               (sender intent vs actual diff)
                                                                  │
                                                             4. patch_test.py
                                                               (build + unit + silicon)
                                                                  │
                                                             5. patch_report.py
                             ←  REVIEW_REPORT.md           ←      │
                                                                  │
SENDER: "LGTM ✅"                                                │
                                                             5. patch_integrate.py
                                                               (cherry-pick → main)
                                                                  │
                                                             Build & ship
```

### Human-Readable Step Chart

| Step | What happens | Main command | Main output |
|------|---------------|--------------|-------------|
| 1 | Receive and validate incoming patches | `python patch_receive.py <incoming-patch-dir>` | Staged patches + `review_data.json` |
| 2 | Apply patches to a review branch | `python patch_apply.py` | Review branch + `apply_data.json` |
| 3 | Check functional equivalence | `python patch_check.py` | Match results + `check_data.json` |
| 4 | Run verification tests | `python patch_test.py` | Build/test status + `test_data.json` |
| 5 | Create report and integrate after LGTM | `python patch_report.py` then `python patch_integrate.py` | `REVIEW_REPORT.md` + changes integrated to working branch |

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `git am` conflict | Fix files, `git add`, `git am --continue`. Or `git am --abort`. |
| Cherry-pick conflict | Fix files, `git add`, `git cherry-pick --continue`. Or `--abort`. |
| MISMATCH in check | Review side-by-side output. Confirm with sender if change is functionally equivalent despite different context. |
| MISSING file | Sender's change may not have applied at all. Check `git am` log and re-apply manually if needed. |
| EXTRA files | Usually fine — receiver adapted context lines. Verify no unintended changes. |

## File Layout

```
repo-root/
├── pyproject.toml             # centralized project/test tool config
├── requirements-dev.txt       # development dependencies (pytest)
├── .patch-pipeline.toml       # config (optional)
├── .patch-staging/
│   └── 2026-03-26/
│       ├── 0001-fix-timing.patch
│       ├── review_data.json    # from step 1
│       ├── apply_data.json     # from step 2
│       ├── check_data.json     # from step 3 ⭐
│       ├── test_data.json      # from step 4
│       └── REVIEW_REPORT.md    # from step 5
└── (your source code)
```

## Running Tests

```bash
python -m pytest tests/ -v
```
