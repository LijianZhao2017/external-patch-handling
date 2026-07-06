# DMR Target Config & HTML-Primary Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the HTML review report the primary reviewer-facing artifact, fix the dead LGTM-approval hint check, add the same hint to the Python integrate path, and correct an inaccurate doc claim about bash report generation.

**Architecture:** No new modules. Four small, independent edits: (1) `bash/patch_integrate.sh`'s Approval Check section gets a working grep pattern and surfaces the HTML report path; (2) `python/patch_report.py`'s `main()` reorders its two `print()` calls; (3) `python/patch_integrate.py` gains a small pure helper + one call site mirroring the bash hint; (4) `.github/copilot-instructions.md` gets one bullet corrected. Each is independently testable/verifiable and independently committable.

**Tech Stack:** Python 3.11 (stdlib `re`, `pathlib`), bash (`grep`), pytest.

**Reference spec:** `docs/superpowers/specs/2026-07-06-dmr-target-and-html-primary-report-design.md`

**Note on the DMR/memoryfirmware target config:** This is documentation-only and was already delivered in the spec doc above (reference `.patch-pipeline.toml` + `--repo` usage). `~/zcodefw/memoryfirmware` does not exist in this environment, so there is no file to create here — nothing further to implement for that part of the spec.

---

### Task 1: Fix the dead LGTM-hint grep and surface the HTML report in bash

**Files:**
- Modify: `bash/patch_integrate.sh:98` (REPORT_FILE declaration) and `bash/patch_integrate.sh:130-142` (Approval Check block)

- [ ] **Step 1: Confirm the current buggy behavior manually**

Run:
```bash
cd /home/lijianzh/cxsh/patch-pipeline
mkdir -p /tmp/lgtm-test
cat > /tmp/lgtm-test/REVIEW_REPORT.md <<'EOF'
## Reviewer Recommendation

- [x] **LGTM** — Ready for sender blessing. Recommend cherry-pick to working branch.
- [ ] **Changes Requested** — See notes above. Sender should revise and resubmit.
EOF
grep -q "LGTM.*✅" /tmp/lgtm-test/REVIEW_REPORT.md && echo MATCHED || echo "NO MATCH (confirms the bug)"
```
Expected: `NO MATCH (confirms the bug)` — proves the current pattern never matches even a ticked checkbox.

- [ ] **Step 2: Replace the REPORT_FILE declaration**

In `bash/patch_integrate.sh`, find:
```bash
REPORT_FILE="$STAGING_DIR/REVIEW_REPORT.md"

log_info "Integrating patches from $DATE"
```
Replace with:
```bash
REPORT_FILE="$STAGING_DIR/REVIEW_REPORT.md"
REPORT_FILE_HTML="$STAGING_DIR/REVIEW_REPORT.html"

log_info "Integrating patches from $DATE"
```

- [ ] **Step 3: Replace the Approval Check block**

Find:
```bash
if [[ -f "$REPORT_FILE" ]]; then
  log_info "Review report available at: $REPORT_FILE"
  echo ""
  if grep -q "LGTM.*✅" "$REPORT_FILE" 2>/dev/null; then
    log_success "Report shows LGTM approval"
  else
    log_warn "Report exists but LGTM status not explicitly marked"
  fi
else
  log_warn "No review report found at $REPORT_FILE"
fi
```
Replace with:
```bash
if [[ -f "$REPORT_FILE_HTML" ]]; then
  log_info "Review report (open this for review): $REPORT_FILE_HTML"
fi

if [[ -f "$REPORT_FILE" ]]; then
  log_info "Review report source (edit this to mark LGTM): $REPORT_FILE"
  echo ""
  if grep -qi -- '- \[x\].*\*\*LGTM\*\*' "$REPORT_FILE" 2>/dev/null; then
    log_success "Report shows LGTM approval (checkbox marked)"
  else
    log_warn "Report exists but LGTM checkbox not marked"
  fi
else
  log_warn "No review report found at $REPORT_FILE"
fi
```

- [ ] **Step 4: Verify the fixed pattern manually**

Run:
```bash
grep -qi -- '- \[x\].*\*\*LGTM\*\*' /tmp/lgtm-test/REVIEW_REPORT.md && echo MATCHED || echo "NO MATCH"
```
Expected: `MATCHED`

Then confirm it correctly does NOT match an unticked box:
```bash
sed 's/\[x\]/[ ]/' /tmp/lgtm-test/REVIEW_REPORT.md > /tmp/lgtm-test/unticked.md
grep -qi -- '- \[x\].*\*\*LGTM\*\*' /tmp/lgtm-test/unticked.md && echo MATCHED || echo "NO MATCH (correct)"
```
Expected: `NO MATCH (correct)`

Clean up: `rm -rf /tmp/lgtm-test`

- [ ] **Step 5: Syntax-check the script**

Run: `bash -n bash/patch_integrate.sh`
Expected: no output, exit code 0

- [ ] **Step 6: Commit**

```bash
git add bash/patch_integrate.sh
git commit -m "fix: correct dead LGTM-hint grep pattern in patch_integrate.sh

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 2: Make the HTML report primary in `patch_report.py` output

**Files:**
- Modify: `python/patch_report.py` (in `main()`, the two `print()` lines near the end, currently ~lines 697-698)
- Test: `tests/test_patch_report.py` (existing tests, run only — no new test needed; they assert file existence/content, not print order)

- [ ] **Step 1: Run existing report tests to confirm current baseline passes**

Run: `python -m pytest tests/test_patch_report.py -v`
Expected: all tests PASS

- [ ] **Step 2: Reorder the print statements**

In `python/patch_report.py`, find:
```python
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    html_out_path.write_text(html_report)
    print(f"📄 Markdown report saved to {out_path}")
    print(f"🌐 HTML report saved to {html_out_path}")
```
Replace with:
```python
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(report)
    html_out_path.write_text(html_report)
    print(f"🌐 HTML report saved to {html_out_path} (open this for review)")
    print(f"📄 Markdown report saved to {out_path} (edit this to mark LGTM)")
```

- [ ] **Step 3: Run the tests again to confirm nothing broke**

Run: `python -m pytest tests/test_patch_report.py -v`
Expected: all tests still PASS (they check file existence/content only, unaffected by print order)

- [ ] **Step 4: Commit**

```bash
git add python/patch_report.py
git commit -m "feat: make HTML the primary reviewer-facing report artifact

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 3: Add the same LGTM hint to `patch_integrate.py` (python/bash parity)

**Files:**
- Modify: `python/patch_integrate.py` (add `import re` near the top, add a new `_print_report_hint` function after `_derive_integrate_branch`, add one call site inside `integrate_patches`)

- [ ] **Step 1: Add the `re` import**

In `python/patch_integrate.py`, find:
```python
import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path
```
Replace with:
```python
import argparse
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path
```

- [ ] **Step 2: Add the hint helper function**

In `python/patch_integrate.py`, find:
```python
def _derive_integrate_branch(review_branch: str, cfg: Config) -> str:
    """Derive integrate/<date>/<slug> from review/<date>/<slug>."""
    parts = review_branch.split("/", 1)
    suffix = parts[1] if len(parts) == 2 else review_branch
    return f"{cfg.integrate_branch_prefix}/{suffix}"


def _create_github_pr(
```
Replace with:
```python
def _derive_integrate_branch(review_branch: str, cfg: Config) -> str:
    """Derive integrate/<date>/<slug> from review/<date>/<slug>."""
    parts = review_branch.split("/", 1)
    suffix = parts[1] if len(parts) == 2 else review_branch
    return f"{cfg.integrate_branch_prefix}/{suffix}"


_LGTM_CHECKED_RE = re.compile(r"-\s*\[x\].*\*\*LGTM\*\*", re.IGNORECASE)


def _print_report_hint(staging_dir: Path) -> None:
    """Print an informational hint about the review report and LGTM status.

    Mirrors bash/patch_integrate.sh's Approval Check section. This never
    blocks the flow — the actual approval gate is the yes/no prompt that
    follows in integrate_patches().
    """
    html_report = staging_dir / "REVIEW_REPORT.html"
    md_report = staging_dir / "REVIEW_REPORT.md"

    if html_report.exists():
        print(f"ℹ️  Review report (open this for review): {html_report}")

    if md_report.exists():
        print(f"ℹ️  Review report source (edit this to mark LGTM): {md_report}")
        if _LGTM_CHECKED_RE.search(md_report.read_text()):
            print("✅ Report shows LGTM approval (checkbox marked)")
        else:
            print("⚠️  Report exists but LGTM checkbox not marked")
    else:
        print(f"⚠️  No review report found at {md_report}")


def _create_github_pr(
```

- [ ] **Step 3: Call the hint before the blessing prompt**

In `python/patch_integrate.py`, find (inside `integrate_patches`):
```python
    # Sender blessing gate
    print(f"\n{'─' * 60}")
    print(f"Integration: {review_branch} → {integrate_branch} → PR → {base_branch}")
    print(f"Commits to cherry-pick: {len(applied)}")
    for c in applied:
        print(f"  {c['hash']}  {c['subject'][:60]}")
    print(f"{'─' * 60}\n")

    try:
        blessed = input("Has the sender blessed these changes? (yes/no): ").strip().lower()
```
Replace with:
```python
    # Sender blessing gate
    print(f"\n{'─' * 60}")
    print(f"Integration: {review_branch} → {integrate_branch} → PR → {base_branch}")
    print(f"Commits to cherry-pick: {len(applied)}")
    for c in applied:
        print(f"  {c['hash']}  {c['subject'][:60]}")
    print(f"{'─' * 60}\n")

    _print_report_hint(staging_dir)

    try:
        blessed = input("Has the sender blessed these changes? (yes/no): ").strip().lower()
```

- [ ] **Step 4: Verify the helper manually (per approved spec — no new automated test)**

Run:
```bash
cd /home/lijianzh/cxsh/patch-pipeline
mkdir -p /tmp/lgtm-py-test
cat > /tmp/lgtm-py-test/REVIEW_REPORT.md <<'EOF'
- [x] **LGTM** — Ready for sender blessing.
EOF
python3 -c "
import sys
sys.path.insert(0, 'python')
from pathlib import Path
from patch_integrate import _print_report_hint
_print_report_hint(Path('/tmp/lgtm-py-test'))
"
```
Expected output includes: `✅ Report shows LGTM approval (checkbox marked)`

Then verify the unticked case:
```bash
cat > /tmp/lgtm-py-test/REVIEW_REPORT.md <<'EOF'
- [ ] **LGTM** — Ready for sender blessing.
EOF
python3 -c "
import sys
sys.path.insert(0, 'python')
from pathlib import Path
from patch_integrate import _print_report_hint
_print_report_hint(Path('/tmp/lgtm-py-test'))
"
```
Expected output includes: `⚠️  Report exists but LGTM checkbox not marked`

Clean up: `rm -rf /tmp/lgtm-py-test`

- [ ] **Step 5: Run the existing branch-flow tests to confirm no regression**

Run: `python -m pytest tests/test_branch_flow.py -v`
Expected: all tests PASS (they only exercise `_derive_integrate_branch` and branch helpers, unaffected by this change)

- [ ] **Step 6: Run the full test suite**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 7: Commit**

```bash
git add python/patch_integrate.py
git commit -m "feat: add LGTM report hint to patch_integrate.py (bash parity)

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 4: Correct the inaccurate bash-report-generation claim in copilot-instructions.md

**Files:**
- Modify: `.github/copilot-instructions.md` (the "Integration Flow (Step 5)" section, "Asymmetry" bullet)

- [ ] **Step 1: Replace the inaccurate bullet**

In `.github/copilot-instructions.md`, find:
```markdown
- **Asymmetry**: Python has separate `patch_report.py` (Markdown + HTML) and `patch_integrate.py`. The bash version has no `patch_report.sh` — `bash/patch_integrate.sh` generates and prints the report path inline before integrating
```
Replace with:
```markdown
- **Asymmetry**: Python has separate `patch_report.py` (Markdown + HTML) and `patch_integrate.py`. There is no `bash/patch_report.sh` — bash never generates a report at all. `bash/patch_integrate.sh` only checks whether `REVIEW_REPORT.md`/`.html` already exist (from a prior Python `patch_report.py` run) and prints an informational LGTM-checkbox hint before the approval prompt; it does not generate them. This is a known, undocumented-until-now gap (see `docs/superpowers/specs/2026-07-06-dmr-target-and-html-primary-report-design.md`), not something this change fixes
```

- [ ] **Step 2: Proofread the surrounding section**

View `.github/copilot-instructions.md` lines 79-91 and confirm the replaced bullet reads correctly in context (no dangling references, consistent tone with neighboring bullets).

- [ ] **Step 3: Commit**

```bash
git add .github/copilot-instructions.md
git commit -m "docs: correct inaccurate claim about bash report generation

Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>"
```

---

### Task 5: Final verification and push

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite one more time**

Run: `python -m pytest tests/ -v`
Expected: all tests PASS

- [ ] **Step 2: Review the full diff across all four tasks**

Run: `git log --oneline -5 && git --no-pager diff origin/main..HEAD --stat`
Expected: 4 commits shown (Tasks 1-4), touching exactly `bash/patch_integrate.sh`, `python/patch_report.py`, `python/patch_integrate.py`, `.github/copilot-instructions.md`

- [ ] **Step 3: Push**

Run: `git push`
Expected: push succeeds, `main` updated on origin
