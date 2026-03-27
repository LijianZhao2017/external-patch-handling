# Bash Scripts — Quick Start

Use these lightweight bash versions instead of Python for faster startup and zero dependencies.

## Install

No installation needed! Scripts are executable:

```bash
ls -la patch_*.sh
chmod +x patch_*.sh  # if needed
```

## Configuration

Same as Python version. Create `.patch-pipeline.toml`:

```toml
release = "BHS-B0"
working_branch = "main"
build_command = "make -j$(nproc)"
unit_test_command = "pytest tests/"
```

Or use environment variables:

```bash
export PATCH_PIPELINE_WORKING_BRANCH="develop"
export PATCH_PIPELINE_BUILD_COMMAND="cargo build"
```

## 5-Step Pipeline

### Step 1: Receive Patches
```bash
./patch_receive.sh /path/to/patches/
# or
./patch_receive.sh ./patches/ --date 2026-03-25 --force
```

### Step 2: Apply to Review Branch
```bash
./patch_apply.sh
# or
./patch_apply.sh --date 2026-03-25
```

### Step 3: Check Equivalence ⭐
```bash
./patch_check.sh
# Shows: MATCH | PARTIAL | MISMATCH | MISSING | EXTRA
```

### Step 4: Run Tests
```bash
./patch_test.sh
# Runs: build + unit tests + prompts for silicon results
```

### Step 5: Integrate After Approval
```bash
./patch_integrate.sh
# Cherry-picks to working branch
```

## Common Options

All scripts support:

```bash
--date YYYY-MM-DD     # Specify staging date
--repo /path/to/repo  # Specify repo path
--help                # Show usage
```

## Mixing Python & Bash

Use whichever you prefer per step:

```bash
# Bash for lightweight receive
./patch_receive.sh ./patches/

# Python for detailed checks
python patch_apply.py
python patch_check.py

# Bash for speed
./patch_test.sh
./patch_integrate.sh
```

Both generate compatible JSON, so they work together seamlessly.

## Key Differences vs Python

| Aspect | Bash | Python |
|--------|------|--------|
| Startup | Fast (~50ms) | Slower (~500ms) |
| Dependencies | Zero | Python 3.11+ |
| Validation | Basic | Comprehensive |
| Path filtering | Not implemented | ✅ |
| Interactive notes | Not implemented | ✅ |
| Similarity scoring | Simplified | Advanced |

For most workflows, bash and Python produce equivalent results. See **BASH_IMPLEMENTATION.md** for detailed feature comparison.

## Troubleshooting

| Problem | Fix |
|---------|-----|
| `patch_apply.sh not found` | Run `chmod +x patch_*.sh` |
| `git am --3way conflict` | Fix files, run `git add`, then `git am --continue` |
| `No .patch files found` | Check path: `ls -la /path/to/patches/` |
| `Working tree is not clean` | Stash changes: `git stash` |

For detailed help on each script, see **BASH_README.md**.

## Performance

- **Startup:** Bash is 10x faster (negligible for typical workflows)
- **Git operations:** Same speed (git is the bottleneck)
- **Overall:** No significant difference for real-world usage

## Next Steps

1. **Try it:** Run `./patch_apply.sh --help` to see options
2. **Mix & match:** Use bash where you prefer, Python elsewhere
3. **Report issues:** File bug reports with script output and git log
4. **Contribute:** Improve bash scripts via pull requests

---

**Get started:** `./patch_receive.sh ./your-patches/`
