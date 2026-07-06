# DMR Target Config & HTML-Primary Reporting

**Date:** 2026-07-06
**Status:** Approved (pending implementation)

## Problem

1. The pipeline needs to support a new target repo: the DMR project/platform,
   whose source lives at `~/zcodefw/memoryfirmware` on branch `main`. That
   path does not exist in every environment (e.g. this sandbox), so the
   deliverable here is a documented reference config, not a code change.

2. The review report is generated in both Markdown and HTML
   (`patch_report.py`), but the pipeline treats Markdown as primary and the
   sender-approval "hint" check is broken: `bash/patch_integrate.sh` greps
   the report for the literal string `LGTM.*✅`, which is never produced by
   either the Markdown (`- [ ] **LGTM**`) or HTML (`<input type="checkbox">
   ... LGTM`) generators. The hint always falls through to "not explicitly
   marked." This is informational only — the real approval gate is the
   `input()` yes/no prompt in both `patch_integrate.py` and
   `patch_integrate.sh` — but the hint should still work.

3. While investigating, we also found `bash/patch_integrate.sh` never
   generates a report at all — it only checks whether `REVIEW_REPORT.md`
   already exists. There is no `bash/patch_report.sh`. Report generation is
   Python-only today, despite docs implying bash/Python parity across all 5
   steps. Fixing that parity gap is explicitly **out of scope** for this
   change (tracked here as a known gap only) — we're only correcting the
   inaccurate doc claim, not adding bash report generation.

## Scope

**In scope:**
- Reference `.patch-pipeline.toml` for the DMR/memoryfirmware target (docs).
- Make the HTML report the primary reviewer-facing artifact in output
  messaging (Python) and in `bash/patch_integrate.sh`'s approval-check
  section; keep generating both formats (no format is removed).
- Fix the broken LGTM-hint detection in `bash/patch_integrate.sh` to check
  for the real generated checkbox-checked syntax (`- [x] **LGTM**`) in
  `REVIEW_REPORT.md`.
- Add the equivalent informational hint to `patch_integrate.py` (it
  currently has none), for python/bash parity on this one behavior.
- Correct the inaccurate claim in `.github/copilot-instructions.md` that
  `bash/patch_integrate.sh` generates the report.

**Out of scope:**
- No interactive/persisted HTML approval (e.g. a clickable checkbox that
  saves state). HTML checkboxes remain view-only; the checkbox tick in
  `REVIEW_REPORT.md` is what a sender would hand-edit, and the yes/no prompt
  remains the actual gate.
- No `bash/patch_report.sh` (bash report generation). Documented as a known
  gap, not fixed here.
- No first-class "named target repo" / profile registry. `--repo` +
  per-target `.patch-pipeline.toml` already covers this need.
- No code changes required to support arbitrary target repo paths — verified
  the codebase has no hardcoded paths (`repo_path` is threaded through
  consistently; the one `~/OKS/MemoryFirmware` mention in `utils.py` is a
  docstring example, not logic).

## Design

### 1. DMR/memoryfirmware target config (docs only)

Once `~/zcodefw/memoryfirmware` exists locally (git repo on `main`), place a
`.patch-pipeline.toml` at its root:

```toml
release = "DMR"
base_branch = "main"   # explicit: prevents resolved_working_branch from
                        # falling back to "release/DMR" (the release/<name>
                        # fallback only applies when base_branch is unset)
```

`build_command` / `unit_test_command` are left unset (blank = skip), per
current requirements. Every pipeline step is invoked with
`--repo ~/zcodefw/memoryfirmware` (or run with that directory as cwd), e.g.:

```bash
python python/patch_receive.py /path/to/dmr/patches/ --repo ~/zcodefw/memoryfirmware
python python/patch_apply.py --repo ~/zcodefw/memoryfirmware
```

No pipeline code changes are needed for this part — `Config.load(--repo)`
already resolves `.patch-pipeline.toml` from inside the target repo, and
`staging_path` (`.patch-staging/`) lives inside that same target repo, so
staging data for DMR is automatically isolated from any other target (e.g.
`~/OKS/Intel`, `~/OKS/MemoryFirmware`).

### 2. HTML-primary reporting

**`python/patch_report.py` (`main`)** — reorder the two `print()` calls so
the HTML path is presented first and labeled as the one to open for review;
Markdown is labeled as the editable LGTM-checkbox source. Both files are
still written unconditionally; nothing is removed.

**`bash/patch_integrate.sh`** (Approval Check section, ~line 98-142):
- Keep `REPORT_FILE="$STAGING_DIR/REVIEW_REPORT.md"` for the checkbox check
  (only the Markdown twin is realistically hand-edited to mark approval).
- Add `REPORT_FILE_HTML="$STAGING_DIR/REVIEW_REPORT.html"`; if present, print
  it first as "open this for review."
- Replace the dead pattern:
  ```bash
  grep -q "LGTM.*✅" "$REPORT_FILE"
  ```
  with a check for the real checked-checkbox line the generator produces
  once a reviewer hand-edits it:
  ```bash
  grep -qi -- '- \[x\].*\*\*LGTM\*\*' "$REPORT_FILE"
  ```
- Behavior is still informational only — output changes from "Report exists
  but LGTM status not explicitly marked" (always shown today, since the old
  pattern never matched) to an accurate reflection of whether the checkbox
  was actually ticked.

**`python/patch_integrate.py`** (Sender blessing gate, ~line 93-107): add the
same informational check before the `input()` prompt — read
`REVIEW_REPORT.md` from the staging dir if present, check for `- [x]
**LGTM**` (case-insensitive), and print a matching hint line. This mirrors
the bash behavior; the actual gate (the `input()` call) is unchanged.

### 3. Documentation correction

`.github/copilot-instructions.md`'s "Integration Flow (Step 5)" section
currently states: *"the bash version has no `patch_report.sh` —
`bash/patch_integrate.sh` generates and prints the report path inline before
integrating."* This is inaccurate — bash never generates a report, only
checks for one. Correct this bullet to state plainly that bash has no report
generation step at all (a known gap, not fixed by this change) and that
`bash/patch_integrate.sh` only checks for a pre-existing report.

## Testing

- No existing test exercises the `.sh` scripts (checked: no
  subprocess-driven bash tests in `tests/`), so the `bash/patch_integrate.sh`
  grep-pattern fix is validated manually during implementation (construct a
  sample `REVIEW_REPORT.md` with the checkbox both ticked and unticked,
  confirm the grep matches/doesn't match as expected) rather than added to
  the pytest suite.
- `patch_integrate.py`'s new hint is a print-only addition with no branching
  effect on the actual gate (the `input()` call is unchanged); validated
  manually, no new automated test added.
