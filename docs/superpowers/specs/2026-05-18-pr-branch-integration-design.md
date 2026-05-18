# PR Branch Integration Design

**Date:** 2026-05-18  
**Status:** Implemented

## Problem

The previous `patch_integrate.py` cherry-picked commits directly onto the
working branch (`main` / `release/...`) and left the user to push manually.
This bypassed normal GitHub PR review, gave reviewers no opportunity to comment,
and produced no audit trail in the PR history.

## Solution

Replace the direct cherry-pick-to-working-branch flow with a three-step finish:

1. Create `integrate/<date>/<slug>` from the working branch
2. Cherry-pick commits from the review branch onto it
3. Push to origin and open a GitHub PR via `gh pr create`

The working branch only receives commits through the standard PR merge flow.

## Architecture

```
review/<date>/<slug>  (existing, patches applied)
        │
        │  cherry-pick (patch_integrate.py)
        ▼
integrate/<date>/<slug>  (new branch from working branch)
        │
        │  git push origin + gh pr create
        ▼
    GitHub PR  →  merge  →  main / release/...
```

## Components Changed

### `python/config.py`
- Added `integrate_branch_prefix: str = "integrate"` field
- Configurable via `.patch-pipeline.toml` or `PATCH_PIPELINE_INTEGRATE_BRANCH_PREFIX` env var

### `python/patch_integrate.py`
- `_derive_integrate_branch(review_branch, cfg)` — strips first path segment and prepends integrate prefix
- `_create_github_pr(repo, integrate_branch, base_branch, applied)` — calls `gh pr create`, returns PR URL or None
- `integrate_patches()` — new flow: checkout base → create integrate branch → cherry-pick → push → gh pr create → write `integrate_data.json`
- Graceful fallback when `gh` CLI is not installed (prints manual command)

### `bash/patch_integrate.sh`
- Mirrors Python changes: derives integrate branch with `${REVIEW_BRANCH#*/}`, creates branch, pushes, calls `gh pr create`
- Reads `PATCH_PIPELINE_INTEGRATE_BRANCH_PREFIX` env var (default: `integrate`)

### `tests/test_branch_flow.py`
- `test_derive_integrate_branch_standard` — basic slug derivation
- `test_derive_integrate_branch_complex_slug` — longer slugs
- `test_derive_integrate_branch_custom_prefix` — TOML override
- `test_derive_integrate_branch_env_override` — env var override
- `test_integrate_branch_prefix_default` — default value check
- `test_integrate_branch_prefix_from_toml` — TOML loading

### Docs
- `BRANCHING_STRATEGY.md` — updated flow diagram to three-branch model
- `README.md` — updated Step 5 description and troubleshooting table

## Data Flow

```
.patch-staging/<date>/
├── apply_data.json       # source: review branch + commit hashes
└── integrate_data.json   # new: integrate branch + PR URL
```

## Error Handling

| Scenario | Behaviour |
|----------|-----------|
| Integrate branch already exists | Exit with message: `git branch -D <branch>` |
| Cherry-pick conflict | Offer abort/continue, exit 1 on conflict |
| Push failure | Warn + print manual push command, continue to PR step |
| `gh` not installed | Warn + print `gh pr create ...` command, exit 0 |
| `gh pr create` fails | Warn + print fallback command |

## Configuration

```toml
# .patch-pipeline.toml
integrate_branch_prefix = "integrate"   # default; change to "pr" etc.
```

```bash
export PATCH_PIPELINE_INTEGRATE_BRANCH_PREFIX=pr
```
