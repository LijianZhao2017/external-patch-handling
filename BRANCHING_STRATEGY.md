# Branching Strategy — Patch Review Pipeline

## Why This Pipeline Exists

In a distributed BIOS/firmware development workflow, patch exchange between
sender and receiver teams often involves **raw diffs** — plain `git diff` or
unified diff output without proper commit metadata. These files:

- ❌ Lack `From`/`Subject:` headers — `git am` rejects them
- ❌ Use mixed formats — some have `diff --git` headers, others are bare `--- a/` unified diffs
- ❌ Overlap across versions — multiple diffs touch the same files with evolving changes
- ❌ Carry no author or date information — provenance is lost

**Example** (historical raw diffs from this project):

| File | Format | `diff --git`? | `From:`/`Subject:`? | Files |
|------|--------|:-------------:|:-------------------:|:-----:|
| `0726.patch` | plain git diff | ✅ | ❌ | 6 |
| `IntelPatch20250528.diff` | bare unified diff | ❌ | ❌ | 4 |
| `IntelPatch20250626_GnrSp.diff` | bare unified diff | ❌ | ❌ | 4 |
| `Patch_0813.diff` | plain git diff | ✅ | ❌ | 8 |

The pipeline standardizes on **`git format-patch`** output to solve these
problems. All incoming patches must include proper commit headers for
traceability, automated application, and conflict resolution.

---

## Two-Branch Strategy

The pipeline uses three branch roles with distinct responsibilities:

```
                    SENDER
                      │
                git format-patch
                      │
                      ▼
┌─────────────────────────────────────────────────┐
│           REVIEW BRANCH (disposable)            │
│         review/<date>/<patch-slug>               │
│                                                 │
│  • Landing zone for incoming patches            │
│  • Created fresh from base branch               │
│  • Patches applied via git am --3way            │
│  • Conflicts resolved here (isolated)           │
│  • Equivalence check runs here                  │
│  • Deleted after integration                    │
└──────────────────────┬──────────────────────────┘
                       │
              sender blessing
              cherry-pick commits
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│         INTEGRATE BRANCH (PR vehicle)           │
│        integrate/<date>/<patch-slug>             │
│                                                 │
│  • Clean branch based on working branch         │
│  • Cherry-picked commits from review branch     │
│  • Pushed to origin, opened as GitHub PR        │
│  • Merged by PR review process                  │
│  • Deleted after merge                          │
└──────────────────────┬──────────────────────────┘
                       │
              GitHub PR → merge
                       │
                       ▼
┌─────────────────────────────────────────────────┐
│          WORKING BRANCH (protected)             │
│         main  or  release/<name>                │
│                                                 │
│  • Build and release branch                     │
│  • Only receives blessed commits via PR         │
│  • Never polluted by unreviewed patches         │
│  • Clean history for CI/CD                      │
└─────────────────────────────────────────────────┘
```

### Review Branch — `review/<date>/<slug>`

**Purpose:** Temporary, isolated landing zone for patch evaluation.

- Created from the configured base branch (e.g., `release/bhs_pb2_35d44` or `main`)
- Naming convention: `review/2026-03-26/fix-dfe-gain` (date + slugified subject)
- Patches applied with `git am --3way` preserving author, date, and commit message
- If conflicts occur, they are resolved **on this branch only** — the working
  branch is never touched during review
- After integration, the review branch can be safely deleted

### Integrate Branch — `integrate/<date>/<slug>`

**Purpose:** Clean PR vehicle for merging reviewed commits into the working branch.

- Created from the working branch (same base as the target)
- Naming mirrors the review branch: `review/...` → `integrate/...`
- Receives cherry-picked commits from the review branch
- Pushed to origin and opened as a GitHub PR targeting the working branch
- Merged via standard PR review process; deleted after merge
- Branch prefix configurable via `integrate_branch_prefix` (default: `"integrate"`)

### Working Branch — `main` or `release/<name>`

**Purpose:** Stable branch for builds, testing, and releases.

- Only receives commits that have passed all review gates:
  1. ✅ Format validation (Step 1)
  2. ✅ Clean application (Step 2)
  3. ✅ Functional equivalence check (Step 3)
  4. ✅ Build and test pass (Step 4)
  5. ✅ Sender blessing / approval (Step 5)
- Commits arrive via GitHub PR merge from the integrate branch
- History stays clean — no direct pushes from patch review

---

## End-to-End Flow

```
Step 1: RECEIVE          Step 2: APPLY             Step 3: CHECK
─────────────           ────────────              ─────────────
format-patch   ──►  git am --3way on     ──►  Compare sender intent
validation          review/<date>/<slug>       vs actual receiver diff
                    (from base branch)         Classify per-file:
                                               MATCH/PARTIAL/MISMATCH

Step 4: TEST             Step 5: INTEGRATE
─────────────           ──────────────────────────────────────────
Build + unit tests  ──►  Sender approves
on review branch         cherry-pick commits to integrate/<date>/<slug>
                         push + open GitHub PR → working branch
                         delete review branch after PR merge
```

---

## Branch Configuration

Configured via `.patch-pipeline.toml` or environment variables:

```toml
# .patch-pipeline.toml
release = "bhs_pb2_35d44"
base_branch = "release/bhs_pb2_35d44"    # Working branch (build/release)
```

**Resolution priority** for the working branch:

| Priority | Setting | Example |
|:--------:|---------|---------|
| 1 | `base_branch` (explicit) | `release/bhs_pb2_35d44` |
| 2 | `working_branch` (if not `main`) | `develop` |
| 3 | `release/<release>` (if release set) | `release/bhs_pb2_35d44` |
| 4 | Default | `main` |

---

## Why Three Branches?

| Concern | Review Branch | Integrate Branch | Working Branch |
|---------|:------------:|:----------------:|:--------------:|
| Receives raw patches | ✅ | ❌ | ❌ |
| Conflict resolution happens here | ✅ | ❌ | ❌ |
| Equivalence checking target | ✅ | ❌ | ❌ |
| Opened as GitHub PR | ❌ | ✅ | ❌ |
| Builds and releases | ❌ | ❌ | ✅ |
| Only blessed commits | ❌ | ✅ | ✅ |
| Clean git history | disposable | disposable | ✅ |

**Key benefit:** If a patch set has problems — conflicts, mismatches, or test
failures — the working branch is **completely unaffected**. The review branch
is simply discarded, and the team can retry with a corrected patch set.

The integrate branch keeps the PR process clean: the working branch only ever
receives commits through the normal GitHub PR review flow.

---

## Conflict Resolution

Conflicts are handled at two stages:

### During Apply (Step 2)
- `git am --3way` uses the common ancestor for merge
- If conflicts occur, the pipeline pauses and reports which patch failed
- Resolve conflicts on the review branch, then `git am --continue`
- The working branch is untouched

### During Integration (Step 5)
- `git cherry-pick` from review → integrate branch
- If conflicts occur (rare after equivalence check), the pipeline offers
  abort/continue options
- Only fully clean cherry-picks make it to the integrate branch, which is
  then opened as a GitHub PR targeting the working branch
