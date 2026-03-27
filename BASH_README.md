# Bash Alternatives to Patch Pipeline Scripts

This directory now includes **bash versions** of all Python patch pipeline scripts, providing a lightweight alternative when Python is unavailable or not preferred.

## Overview

| Step | Python Script | Bash Script | Purpose |
|------|---|---|---|
| 1 | `patch_receive.py` | `patch_receive.sh` | Receive, validate, and review patches |
| 2 | `patch_apply.py` | `patch_apply.sh` | Apply patches to a dedicated review branch |
| 3 | `patch_check.py` | `patch_check.sh` | Functional equivalence check (sender intent vs actual) |
| 4 | `patch_test.py` | `patch_test.sh` | Run build + unit tests + silicon test results |
| 5 | `patch_integrate.py` | `patch_integrate.sh` | Cherry-pick reviewed patches to working branch |

## Quick Start (Bash)

```bash
# Configure repo (same as Python version)
cat > .patch-pipeline.toml << 'EOF'
release = "BHS-B0"
working_branch = "main"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
EOF

# Step 1: Receive patches
./patch_receive.sh /mnt/sharepoint/BHS-B0/2026-03-26/

# Step 2: Apply to review branch
./patch_apply.sh

# Step 3: Check equivalence
./patch_check.sh

# Step 4: Run tests
./patch_test.sh

# Step 5: Integrate after approval
./patch_integrate.sh
```

## Why Bash Versions?

**Advantages:**
- ✅ **Zero dependencies** — only requires `bash`, `git`, standard Unix tools
- ✅ **Lightweight** — ~6–9 KB per script vs multi-file Python modules
- ✅ **Direct shell integration** — easier to chain with other bash commands
- ✅ **POSIX-friendly** — runs on macOS, Linux, BSD without modification
- ✅ **Coexist with Python** — choose which to use per invocation

**Trade-offs vs Python versions:**
- Reduced feature scope: focuses on core operations (git, file I/O, tables)
- No static code checks or warnings (can add via shell functions if needed)
- JSON output is minimal but compatible with Python reports
- Manual error handling (less type safety)

## Detailed Usage

### Step 1: `patch_receive.sh`

```bash
# Validate patches from a directory
./patch_receive.sh /path/to/patches/

# Stage under a specific date
./patch_receive.sh /path/to/patches/ --date 2026-03-25

# Force overwrite existing session
./patch_receive.sh /path/to/patches/ --force
```

**Output:**
- Lists each patch with subject, author, file count, +/- stats
- Flags binary files and missing content
- Copies patches to `.patch-staging/<date>/`
- Creates `review_data.json` for downstream steps

### Step 2: `patch_apply.sh`

```bash
# Apply today's staged patches
./patch_apply.sh

# Apply a specific date
./patch_apply.sh --date 2026-03-25

# Use a custom repo path
./patch_apply.sh --repo /path/to/repo
```

**Output:**
- Creates review branch: `review/<date>/<slug>`
- Applies all patches with `git am --3way`
- Pauses on conflict; user can fix and continue
- Saves `apply_data.json` with branch name and commit hashes

**On conflict:**
```bash
# Fix conflicts, then continue
git add <resolved-files>
git am --continue

# Or abort
git am --abort && git checkout main && git branch -D review/...
```

### Step 3: `patch_check.sh` ⭐ **Critical Step**

Compares **what sender intended** (their patches) vs **what actually landed** (git diff).

```bash
./patch_check.sh
./patch_check.sh --date 2026-03-25
./patch_check.sh --verbose   # show detailed diffs
```

**Output Table:**

| Status | File | Sent +/- | Recv +/- | Match % |
|--------|------|----------|----------|---------|
| MATCH | src/fix.c | +10/-2 | +10/-2 | 100% |
| PARTIAL | src/config.h | +5/-1 | +4/-1 | 80% |
| MISMATCH | src/old.c | +20/-5 | +2/-10 | 20% |
| MISSING | src/test.c | +3/-0 | +0/-0 | 0% |
| EXTRA | src/new.c | +0/-0 | +15/-0 | N/A |

**Interpretation:**
- **MATCH** (≥75%) — Same logical change landed correctly
- **PARTIAL** (40–75%) — Change partially present; review with sender
- **MISMATCH** (<40%) — Significant divergence; confirm intent
- **MISSING** — Sender touched but nothing landed
- **EXTRA** — Receiver changed files sender didn't touch (adaptation is OK)

**Output:** `check_data.json` with results for report

### Step 4: `patch_test.sh`

```bash
./patch_test.sh
./patch_test.sh --date 2026-03-25
./patch_test.sh --build-cmd "scons -j4"     # custom build
./patch_test.sh --test-cmd "cargo test"     # custom tests
```

**What it does:**
1. Runs build command (default: `make -j$(nproc)`)
2. Runs unit tests (default: `pytest tests/`)
3. Prompts for silicon/hardware test results (PASS/FAIL/PENDING)
4. Saves results to `test_data.json`

**Output:** Simple PASS/FAIL summary + logs

### Step 5: `patch_integrate.sh`

```bash
./patch_integrate.sh
./patch_integrate.sh --date 2026-03-25
```

**What it does:**
1. Verifies review report exists (optional LGTM check)
2. Confirms integration approval (interactive)
3. Checks out working branch
4. Cherry-picks all review commits to working branch
5. Handles conflicts same as `git am`

**On success:**
```
✅ All commits integrated to main
Next steps:
  1. Verify with: git log --oneline -n 10
  2. Run final validation
  3. Push to remote: git push origin main
```

## Configuration

### Via `.patch-pipeline.toml`
All scripts read the same config file as Python versions:

```toml
release = "BHS-B0"
working_branch = "main"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
allowed_path_prefixes = ["src/", "include/"]
max_patch_size_kb = 5000
```

### Via Environment Variables
Override any config setting:

```bash
export PATCH_PIPELINE_WORKING_BRANCH="develop"
export PATCH_PIPELINE_RELEASE="BHS-B1"
export PATCH_PIPELINE_BUILD_COMMAND="cargo build"
export PATCH_PIPELINE_UNIT_TEST_COMMAND="cargo test"

./patch_apply.sh
./patch_test.sh
```

## Mixing Python and Bash

The scripts are **compatible** — you can freely mix:

```bash
# Use Python for receive (more thorough validation)
python patch_receive.py ./patches/

# Apply with bash (lightweight)
./patch_apply.sh

# Check equivalence with Python (detailed analysis)
python patch_check.py

# Test with bash
./patch_test.sh

# Integrate with Python
python patch_integrate.py
```

Both generate the same JSON output files (`.patch-staging/<date>/*.json`), so the pipeline works regardless of which language you use per step.

## Error Handling

### Common Issues

**`No .patch files found`**
```bash
# Verify patch directory has .patch files
ls -la /path/to/patches/
```

**`Working tree is not clean`**
```bash
# Stash or commit changes first
git stash
./patch_apply.sh
```

**`Branch already exists`**
```bash
# Delete old review branch
git branch -D review/2026-03-26/fix-timing
./patch_apply.sh
```

**`git am --3way` conflict**
```bash
# Manually resolve
git add <fixed-files>
git am --continue
# Script will resume
```

**`Test failures`**
- Check `/tmp/build.log` for build errors
- Check `/tmp/test.log` for test failures
- Fix issues on review branch, test again

## Script Internals

Each script:
1. **Sources config** from `.patch-pipeline.toml` or env vars (bash doesn't natively parse TOML; scripts extract key values with grep)
2. **Validates prerequisites** (clean worktree, patch files, staging dirs)
3. **Executes core git commands** (`git am`, `git cherry-pick`, `git diff`)
4. **Generates JSON outputs** for downstream tools
5. **Handles errors gracefully** with clear, actionable messages

### Code Organization

```bash
# Standard structure in each script:
set -euo pipefail          # Fail on error, undefined vars, pipe errors

# Configuration section
REPO_PATH="${REPO_PATH:-.}"
DATE="${DATE:-$(date +%Y-%m-%d)}"
# ... parse --args

# Helper functions
die() { echo "❌ $*" >&2; exit 1; }
log_success() { echo "✅ $*"; }
git_run() { git --no-pager -C "$REPO_PATH" "$@"; }
# ... other helpers

# Validation section
[[ -d "$REPO_PATH" ]] || die "..."

# Core logic
# ... do work

# Output section
echo "$JSON_DATA" | tee "$OUTPUT_FILE"
```

## Testing the Bash Scripts

To verify bash scripts work with your repository:

```bash
# Create a test patch
git format-patch -1 -o ./test-patches/ HEAD

# Test pipeline
mkdir -p .patch-staging/$(date +%Y-%m-%d)
./patch_receive.sh ./test-patches/

./patch_apply.sh

./patch_check.sh

# Clean up test
git branch -D review/*/test-* || true
```

## Limitations of Bash vs Python

| Feature | Python | Bash |
|---------|--------|------|
| Rich validation | ✅ | ⚠️ Basic |
| Static code checks | ✅ | ❌ |
| JSON generation | ✅ Full | ✅ Minimal |
| Path filtering | ✅ | ⚠️ Simple regex |
| Error messages | ✅ Detailed | ✅ Clear |
| Dependency checks | ✅ | ❌ |
| Performance | ⚠️ Slower startup | ✅ Fast |

## Contributing

To improve bash scripts:
1. Fix bugs with `set -euo pipefail` discipline
2. Add new validation checks as helper functions
3. Keep JSON output compatible with Python versions
4. Test on macOS and Linux
5. Document deviations from Python behavior

---

**Summary:** Use bash scripts when you want lightweight, zero-dependency patch management. Use Python versions when you need advanced validation and analysis. Both coexist peacefully in the same pipeline.
