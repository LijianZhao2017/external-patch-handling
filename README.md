# Patch Review Pipeline — One-Page Process Guide

## Quick Start

> **Requirements:** Python 3.11+, git (receiver side only)

Configure your repo by creating `.patch-pipeline.toml` in the repo root:

```toml
release = "BHS-B0"
working_branch = "main"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
```

Or use environment variables: `PATCH_PIPELINE_RELEASE=BHS-B0`, etc.

---

## The 5 Steps

### Step 1 — Receive & Review Patches
```bash
python patch_receive.py /mnt/sharepoint/BHS-B0/2026-03-26/
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
# → Upload report to SharePoint, send to sender for blessing
python patch_integrate.py       # after sender says LGTM
```
Report includes: patches table, equivalence check results, test results, LGTM checkbox. Integration cherry-picks from review branch to working branch after confirming sender blessing.

---

## Flow Diagram

```
SENDER                        SHAREPOINT                      RECEIVER
──────                        ──────────                      ────────
git format-patch           →  /BHS-B0/2026-03-26/         ←  1. patch_receive.py
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
your-repo/
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
