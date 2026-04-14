# Patch Pipeline — Real-World Hardening Design

**Date:** 2026-04-14
**Context:** Lessons learned from integrating CXSH EMR patch into `~/OKS/Intel` on `family/server2`

## Problem Statement

The 5-step patch pipeline works for clean, well-formatted patches but fails on real-world vendor submissions. During the CXSH EMR integration, four gaps caused manual intervention at every stage:

1. **CRLF line endings** in the patch file caused `git am --3way` to fail entirely (context mismatch)
2. **Vendor markers** (`//CXSH+`/`//CXSH-`) passed through undetected, required manual cleanup of 10 occurrences
3. **Design document review** was done entirely by hand — comparing patch against PDF spec and existing vendor patterns
4. **Code style issues** (indentation, brace style, trailing whitespace) required multiple fixup rounds; equivalence check strips whitespace by design, making style invisible

## Approach: Modified Approach A — Enhance Existing Steps

Keep the 5-step pipeline identity. Add an **internal prepare sub-phase** between receive and apply that produces a normalized patch artifact while preserving the original for audit.

### Guiding Principles

- **Original patch is immutable** — never modify the staged `.patch` file
- **Prepared patch is derived** — normalized copy used for apply, with a manifest of transforms
- **Whitespace-ignore is a fallback**, not a default — try strict apply first
- **Style is separate from equivalence** — different section in report, different data structure
- **Detection always; auto-fix only when configured** — vendor markers warn by default, strip only if `vendor_marker_action = "strip"` in config

---

## Design

### 1. New Config Fields (`config.py`)

```python
@dataclass
class Config:
    # ... existing fields ...

    # Line ending normalization (Step 1→2)
    normalize_line_endings: bool = True

    # Vendor marker detection (Step 1)
    vendor_marker_patterns: list[str] = field(default_factory=lambda: [
        r"//\w+\+\s*$",   # //CXSH+, //VENDOR+
        r"//\w+-\s*$",    # //CXSH-, //VENDOR-
    ])
    vendor_marker_action: str = "warn"  # "warn" | "strip"

    # Design document references (metadata for report)
    design_docs: list[str] = field(default_factory=list)
```

**Env var overrides:**
- `PATCH_PIPELINE_NORMALIZE_LINE_ENDINGS=false`
- `PATCH_PIPELINE_VENDOR_MARKER_ACTION=strip`
- `PATCH_PIPELINE_DESIGN_DOCS=/path/to/spec.pdf,/path/to/another.pdf`

**Config.load() type handling additions:**
- `bool` fields: parse via `val.lower() in ("1", "true", "yes")`
- `list[str]` fields: split by comma (like existing `allowed_path_prefixes`)
- `vendor_marker_action`: validate against `("warn", "strip")`, raise on unknown

**TOML example:**
```toml
normalize_line_endings = true
vendor_marker_patterns = ["//\\w+\\+\\s*$", "//\\w+-\\s*$"]
vendor_marker_action = "strip"
design_docs = ["docs/spec.pdf"]
```

### 2. New Utility Functions (`utils.py`)

#### `detect_crlf(path: Path) -> bool`
Returns `True` if the file contains `\r\n` sequences. Reads first 8KB in binary mode.

#### `normalize_line_endings(text: str) -> str`
Converts `\r\n` → `\n` in already-decoded text. Returns the text unchanged if no CRLF found.
**Note:** Do NOT use for patch file normalization — use `normalize_patch_file()` instead, which operates in binary mode to avoid decode/encode round-trip corruption.

#### `normalize_patch_file(src: Path, dest: Path) -> dict`
Reads `src` in **binary mode**, performs `b"\r\n"` → `b"\n"` byte replacement (no decode/encode round-trip — safe for non-ASCII author names and commit messages), writes to `dest`. Returns a manifest dict:
```python
{"original": str(src), "prepared": str(dest), "crlf_normalized": True, "original_size": 1234, "prepared_size": 1200}
```

#### `detect_vendor_markers(text: str, patterns: list[str]) -> list[dict]`
Scans patch content for vendor marker lines. Returns list of `{"line_num": N, "text": "//CXSH+", "pattern": "..."}`. Only scans added lines (`+` prefix in diff hunks) — not commit messages.

#### `strip_vendor_markers(path: Path, patterns: list[str]) -> int`
Removes lines matching vendor marker patterns from **source code files** (not patches). Used post-apply as a fixup commit when `vendor_marker_action = "strip"`. Reads/writes in binary mode (`read_bytes()`/`write_bytes()`) to preserve line endings. Returns count of removed lines.

### 3. Step 1 Enhancement — `patch_receive.py`

**New static checks in `_static_checks()`:**

- **CRLF detection**: Flag if patch file has CRLF. Severity: warning (informational, will be normalized in prepare phase).
- **Vendor marker detection**: Scan added lines for configured patterns. Severity: warning (default). If `vendor_marker_action = "strip"`, stripping is deferred to post-apply (see Step 2 Enhancement) to avoid hunk header rewriting.

**New `--design-doc` CLI argument:**
```
python patch_receive.py /patches/ --design-doc ~/cxsh/0331.pdf
```
Stores document references in `review_data.json` under `"design_docs"` key. These are paths/descriptions, not parsed content. Multiple `--design-doc` flags allowed. Also reads from config `design_docs` field.

**Prepare sub-phase** (runs after validation, before staging complete):

1. For each valid patch, create a copy under `prepared/` subdirectory (same filename, different dir)
2. Apply transforms to the prepared copy:
   - CRLF→LF normalization (if `normalize_line_endings = True`) — **binary** `b"\r\n"` → `b"\n"` replacement, no decode/encode round-trip to avoid corrupting non-ASCII content
   - Vendor marker warning detection (always)
   - Note: vendor marker stripping from patches is deferred — "strip" mode will operate post-apply as a fixup commit to avoid hunk header rewriting complexity
3. Write `prepared/manifest.json` recording all transforms applied per patch
4. If no transforms needed, prepared copy is identical to original

**Staging directory layout change:**
```
.patch-staging/2026-04-14/
├── 0001-fix-timing.patch              # original (immutable)
├── prepared/                          # normalized copies (used by Step 2)
│   ├── 0001-fix-timing.patch          # same name, normalized
│   └── manifest.json                  # transform audit log
├── review_data.json                   # existing
├── apply_data.json                    # existing (Step 2)
├── check_data.json                    # existing (Step 3)
├── test_data.json                     # existing (Step 4)
└── REVIEW_REPORT.md                   # existing (Step 5)
```

This layout avoids the glob collision where `list_patches()` (`directory.glob("*.patch")`) would match both original and prepared patches if they were siblings.

### 4. Step 2 Enhancement — `patch_apply.py`

**Use prepared patch:** Read from `prepared/<name>.patch` if the `prepared/` subdirectory exists, otherwise fall back to the original `.patch`.

**Apply strategy — strict-then-fallback:**
1. Try `git am --3way` with prepared patch
2. On failure: run `git am --abort` to clean up, verify worktree is clean, then retry with `git am --3way --ignore-whitespace`
3. On second failure: run `git am --abort`, verify clean worktree, then fallback to `git apply --ignore-whitespace` + manual commit preserving:
   - Author name/email from patch header
   - Author date from patch header
   - Commit subject/body from patch header
4. Record which strategy succeeded in `apply_data.json`:
   ```json
   {"apply_method": "git-am", "whitespace_relaxed": false}
   ```
   or:
   ```json
   {"apply_method": "git-apply-fallback", "whitespace_relaxed": true}
   ```

**Fallback metadata preservation:**
When using `git apply` fallback, extract author/date/subject/body from the patch. Extend `parse_patch_header()` to also return `"body"` — the commit message text between the `Subject:` continuation and the `---` separator (handling RFC 2822 multi-line subjects). Commit with:
```bash
git commit --author="Name <email>" --date="date" -m "subject\n\nbody"
```

### 5. Step 3 Enhancement — `patch_check.py`

**New: Style sub-check (separate from equivalence)**

After computing equivalence, run a style scan on **lines introduced by the patch** (lines with `+` prefix in `git diff base..review` — not the entire file, to avoid false positives from pre-existing issues). Checks:

| Check | Description |
|-------|-------------|
| Trailing whitespace | Lines ending in spaces/tabs before newline |
| Inconsistent line endings | Mixed CRLF/LF within a single file |
| Vendor marker remnants | Patterns from config still present in applied code |

Style warnings are stored in `check_data.json` under a new `"style_warnings"` key:
```json
{
  "files": [...],
  "overall": "PASS",
  "style_warnings": [
    {"file": "MemDfe.c", "line": 64, "type": "vendor_marker", "text": "//CXSH+"},
    {"file": "MemDfe.c", "line": 158, "type": "trailing_whitespace", "text": "  } "}
  ]
}
```

**Style does NOT affect the MATCH/PARTIAL/MISMATCH classification.** It's a separate advisory section.

### 6. Step 5 Enhancement — `patch_report.py`

**New report sections:**

#### "Patch Preparation" section (after "Patches Received")
- Lists transforms applied (CRLF normalization, marker stripping, count)
- Shows apply method used (strict / whitespace-relaxed / fallback)

#### "Design Documents" section (before "Reviewer Recommendation")
- Lists attached reference documents with paths
- Adds checklist items:
  - `[ ] Patch behavior matches design specification`
  - `[ ] Implementation follows existing vendor patterns (e.g., Micron, Hynix)`

#### "Style Warnings" section (after "Functional Equivalence Check")
- Lists style issues found (trailing whitespace, vendor markers, mixed line endings)
- Separate from equivalence — advisory, not blocking

### 7. Bash Parity

All Python changes must have bash equivalents:
- `patch_receive.sh`: Add `dos2unix`-style CRLF detection (`grep -cP '\r$'`), vendor marker grep
- `patch_apply.sh`: Add fallback logic (try `git am`, then `git am --ignore-whitespace`, then `git apply`)
- `patch_check.sh`: Add `grep -n` style checks on applied files
- `patch_integrate.sh` / report: Add new sections

### 8. Test Coverage

New test files and fixtures needed:

| Test File | What It Tests |
|-----------|---------------|
| `test_line_endings.py` | `detect_crlf()`, `normalize_line_endings()`, `normalize_patch_file()` — CRLF patch fixtures |
| `test_vendor_markers.py` | `detect_vendor_markers()`, `strip_vendor_markers()` — pattern matching, edge cases (markers in commit msg vs diff hunks) |
| `test_patch_apply.py` | Apply strategy: strict success, whitespace-fallback, git-apply-fallback, metadata preservation |
| `test_patch_receive.py` | Static checks: CRLF warning, vendor markers, design doc attachment |
| `test_style_check.py` | Trailing whitespace detection, mixed line endings, vendor marker remnants |

Inline fixtures for CRLF patches (bytes-based, not text):
```python
CRLF_PATCH = (
    b"From abc123\r\n"
    b"From: Test <test@example.com>\r\n"
    b"Subject: [PATCH] Fix timing\r\n"
    b"---\r\n"
    b"diff --git a/foo.c b/foo.c\r\n"
    b"--- a/foo.c\r\n"
    b"+++ b/foo.c\r\n"
    b"@@ -1,3 +1,4 @@\r\n"
    b" existing line\r\n"
    b"+//CXSH+\r\n"
    b"+new code\r\n"
    b"+//CXSH-\r\n"
)
```

---

## Out of Scope

- **Automated PDF/spec content parsing** — too unreliable; design docs are metadata/reminders only
- **Automated code formatting** (running `clang-format`, `uncrustify`) — too risky for external vendor code
- **Plugin/hook system** — over-engineering for 4 concrete gaps
- **Restructuring to 6+ steps** — preserves the "5-step pipeline" identity

## Migration

- All changes are backward-compatible
- Existing `.patch-pipeline.toml` files continue to work (new fields have defaults)
- `prepared/` subdirectory is optional — Step 2 falls back to the original `.patch` files if no `prepared/` subdirectory exists
- No database, no new dependencies beyond Python 3.11 stdlib

---

## Summary

| Gap | Where Fixed | Behavior |
|-----|-------------|----------|
| CRLF/LF | Step 1 (prepare) + Step 2 (fallback) | Auto-normalize + retry strategy |
| Vendor markers | Step 1 (detect) + Step 3 (remnant check) | Warn or strip per config |
| Design docs | Step 1 (attach) + Step 5 (report) | Metadata + reviewer checklist |
| Code style | Step 3 (style sub-check) + Step 5 (report) | Advisory warnings, separate from equivalence |
