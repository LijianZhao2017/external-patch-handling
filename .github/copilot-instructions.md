# Copilot Instructions for patch-pipeline

## Project Overview

**patch-pipeline** is a 5-step patch review and integration system for distributed development workflows. It validates patches from a sender, applies them on a receiver's codebase (which may have diverged), performs functional equivalence checking, runs tests, and integrates approved patches.

The system has dual implementations: Python scripts and bash alternatives. Both generate compatible JSON outputs and work interchangeably.

## Architecture

### Core Workflow (5 Steps)

1. **patch_receive.py/sh** — Receive patches from a shared folder, validate format, check for binary files and path violations, stage for downstream processing
2. **patch_apply.py/sh** — Apply staged patches to a dedicated `review/<date>/<slug>` branch using `git am --3way`, pausing on conflicts
3. **patch_check.py/sh** ⭐ **Key** — Compare sender's intended changes (patch) vs. actual receiver changes (git diff). Classify as MATCH/PARTIAL/MISMATCH/MISSING/EXTRA based on similarity thresholds (75%/40%)
4. **patch_test.py/sh** — Run build + unit tests, prompt for silicon test results
5. **patch_report.py/patch_integrate.py/sh** — Generate review report (REVIEW_REPORT.md), integrate after LGTM

### Data Flow

```
.patch-staging/<date>/
├── *.patch                 # Input patches
├── review_data.json        # Step 1: validated patches + metadata
├── apply_data.json         # Step 2: applied commits + branch name
├── check_data.json         # Step 3: ⭐ equivalence results (critical for review)
├── test_data.json          # Step 4: build/unit/silicon results
└── REVIEW_REPORT.md        # Step 5: human-readable report
```

### Key Modules

- **config.py** — Loads settings from `.patch-pipeline.toml` (TOML) and env vars (`PATCH_PIPELINE_*`). Dataclass-based, priority: env > toml > defaults
- **utils.py** — Git wrapper (git_run), patch parsing (parse_patch_header), validation (validate_format_patch), helpers (slugify, format_table, ensure_clean_worktree)
- **patch_check.py** — Core equivalence logic: tokenizes diff content, counts +/- per file, compares sender vs receiver using similarity scoring (_token_similarity, _classify)

## Build, Test & Lint

### Requirements
- Python 3.11+ (for tomllib; backport available with `tomli`)
- git (for git operations)
- Standard Unix tools (bash scripts only)

### Run Tests
```bash
# Full test suite
python -m pytest tests/ -v

# Single test file
python -m pytest tests/test_patch_check.py -v

# Single test function
python -m pytest tests/test_patch_check.py::test_token_similarity -v

# Run with coverage
python -m pytest tests/ --cov=. --cov-report=term-missing
```

### No Official Linter/Formatter
Code follows PEP 8 informally. Use `black` or `ruff` for consistency if adding code:
```bash
black patch_*.py config.py utils.py
ruff check patch_*.py config.py utils.py
```

### No Build Step
Python scripts are executed directly. Bash scripts are sourced or executed as-is.

## Key Conventions

### Configuration Pattern
- Settings stored in `.patch-pipeline.toml` at repo root (optional)
- Env var overrides: `PATCH_PIPELINE_RELEASE=custom` takes precedence
- Config is always loaded via `Config.load()` from config.py
- Empty build/test commands mean "skip this step"

### Branch Naming
- Review branches: `review/<YYYY-MM-DD>/<slug>` (e.g., `review/2026-03-26/fix-timing`)
- Slug derived from patch subject via `slugify()` (alphanumeric + hyphens, max 50 chars)
- Always checkout working branch before applying (default: `main`)

### JSON Output Compatibility
- All scripts (Python and bash) write to `.patch-staging/<date>/*.json`
- Schemas are loose (dict/object); downstream steps read what they need
- Allows Python step 1 → bash step 2 → Python step 3, etc.

### Equivalence Thresholds (patch_check.py)
- **MATCH** ≥75% token similarity: confident no review needed
- **PARTIAL** 40–75%: manual review recommended
- **MISMATCH** <40%: likely functional divergence
- **MISSING**: sender touched, receiver changed nothing
- **EXTRA**: receiver changed files sender didn't touch (adaptation is normal)

### Error Handling
- Git errors raised as `GitError` with command + stderr for clarity
- File validation returns (bool, reason) tuples, not exceptions
- Script entry points check results explicitly and exit with clear messages
- Bash scripts use `set -euo pipefail` + die() helper

### Patch Format Validation
- Must have `From`/`From:` header (first 10 lines)
- Must have `Subject:` header (first 20 lines)
- Must contain `diff --git` (actual diff content)
- Uses `validate_format_patch()` from utils.py

### Static Checks (on receive)
- Flag binary files (`.bin`, `.exe`, `.dll`, `.o`, `.rom`, etc.)
- Enforce allowed path prefixes if `allowed_path_prefixes` set in config
- Warnings are informational; don't block staging

### Staging Directory Layout
- Single staging dir (default `.patch-staging/`)
- Subdirs by date: `<date>/` (YYYY-MM-DD format)
- Multiple patch batches coexist independently
- Date usually derived from shared folder path or `--date` flag

## Testing Patterns

### Test Structure
- `test_config.py` — Config loading from env/toml, defaults
- `test_utils.py` — Patch parsing (headers, files, stats), validation, formatting
- `test_patch_check.py` — Diff parsing, token similarity scoring, classification

### Common Test Pattern
```python
# Typically use tmp_path fixture for repo operations
def test_something(tmp_path, monkeypatch):
    monkeypatch.setenv("PATCH_PIPELINE_RELEASE", "test-release")
    cfg = Config.load(repo_path=tmp_path)
    assert cfg.release == "test-release"
```

### Inline Diff Test Fixtures
Patches defined as multi-line strings (e.g., SIMPLE_DIFF, TWO_FILE_DIFF in test_patch_check.py) for isolated testing of equivalence logic.

## Common Tasks

### Adding a New Step
1. Create `patch_step_X.py` following existing script structure (argparse, Config.load, step logic, JSON output)
2. Create parallel `patch_step_X.sh` bash version
3. Add tests in `tests/test_step_X.py` (fixture patches, expected JSON output)
4. Update README.md and BASH_README.md with step description
5. Update pipeline diagram in docs

### Modifying Config Fields
1. Add field to `Config` dataclass in config.py (type-hint it)
2. Add env var override in `Config.load()` if non-string type
3. Update `.patch-pipeline.toml` example in README.md
4. Add test case to `tests/test_config.py`

### Fixing Equivalence Logic
- Core similarity scoring in `patch_check.py`: `_token_similarity(sent, recv)` returns 0–1
- Per-file classification in `_classify(match_pct)` based on thresholds
- Diff parsing in `_parse_diff_into_files(diff_text)` → dict[str, (added, removed)]
- Test with `test_patch_check.py` fixtures; update thresholds carefully (affects LGTM decisions)

## Documentation Files

- **README.md / README_CN.md** — User-facing overview and 5-step guide
- **BASH_README.md / BASH_README_CN.md** — Detailed bash script docs + usage
- **BASH_QUICKSTART.md / BASH_QUICKSTART_CN.md** — Quick start for bash
- **BASH_SCRIPTS_INDEX.md** — Navigation guide for bash documentation
- **BASH_IMPLEMENTATION.md** — Technical comparison of Python vs bash feature parity
