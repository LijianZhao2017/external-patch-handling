#!/bin/bash
# Step 2: Apply patches to a dedicated review branch (bash version)
#
# Usage:
#     ./patch_apply.sh                       # apply today's staged patches
#     ./patch_apply.sh --date 2026-03-25     # apply a specific date's patches
#     ./patch_apply.sh --repo /path/to/repo  # apply to specific repo
#
# Environment variables (override defaults):
#     PATCH_PIPELINE_RELEASE (e.g., "BHS-B0")
#     PATCH_PIPELINE_WORKING_BRANCH (e.g., "main")
#     PATCH_PIPELINE_REVIEW_BRANCH_PREFIX (e.g., "review")

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_PATH="${REPO_PATH:-.}"
DATE="${DATE:-$(date +%Y-%m-%d)}"
RELEASE="${PATCH_PIPELINE_RELEASE:-}"
BASE_BRANCH="${PATCH_PIPELINE_BASE_BRANCH:-}"
WORKING_BRANCH="${PATCH_PIPELINE_WORKING_BRANCH:-main}"
REVIEW_PREFIX="${PATCH_PIPELINE_REVIEW_BRANCH_PREFIX:-review}"
STAGING_PATH="${STAGING_PATH:-.patch-staging}"

# Parse command-line arguments
while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      DATE="$2"
      shift 2
      ;;
    --repo)
      REPO_PATH="$2"
      shift 2
      ;;
    --help)
      sed -n '2,/^$/p' "$0" | sed 's/^# //'
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
  esac
done

# ============================================================================
# Helper functions
# ============================================================================

die() {
  echo "❌ $*" >&2
  exit 1
}

log_info() {
  echo "ℹ️  $*"
}

log_success() {
  echo "✅ $*"
}

log_warn() {
  echo "⚠️  $*"
}

git_run() {
  git --no-pager -C "$REPO_PATH" "$@"
}

# Extract subject from patch file header
get_patch_subject() {
  local patch_file="$1"
  grep -m1 "^Subject:" "$patch_file" | sed 's/^Subject: \[PATCH[^]]*\] *//' | cut -c1-60
}

# Simple URL slugify: convert to lowercase, replace non-alphanumeric with dash
slugify() {
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g' | sed 's/^-*//; s/-*$//' | cut -c1-50
}

resolve_base_branch() {
  if [[ -n "$BASE_BRANCH" ]]; then
    echo "$BASE_BRANCH"
  elif [[ "$WORKING_BRANCH" != "main" ]]; then
    echo "$WORKING_BRANCH"
  elif [[ -n "$RELEASE" && "$RELEASE" != "release-name" ]]; then
    echo "release/$RELEASE"
  else
    echo "$WORKING_BRANCH"
  fi
}

ensure_local_branch() {
  local branch="$1"
  if git_run show-ref --verify --quiet "refs/heads/$branch"; then
    return 0
  fi
  if git_run show-ref --verify --quiet "refs/remotes/origin/$branch"; then
    git_run branch --track "$branch" "origin/$branch" > /dev/null
    return 0
  fi
  die "Base branch '$branch' not found locally or as origin/$branch"
}

detect_patch_root_prefix() {
  local patch_file="$1"
  local repo_name
  repo_name=$(basename "$REPO_PATH")
  mapfile -t files < <(grep "^diff --git" "$patch_file" | sed 's|^diff --git a/||; s| b/.*||' | sort -u)
  if [[ ${#files[@]} -eq 0 ]]; then
    return 1
  fi
  for file in "${files[@]}"; do
    [[ "$file" == "$repo_name/"* ]] || return 1
    stripped="${file#"$repo_name/"}"
    [[ ! -e "$REPO_PATH/$file" && -e "$REPO_PATH/$stripped" ]] || return 1
  done
  echo "$repo_name"
}

prepare_patch_for_repo() {
  local patch_file="$1"
  local prefix=""
  prefix=$(detect_patch_root_prefix "$patch_file" || true)
  if [[ -n "$prefix" ]]; then
    local temp_patch
    temp_patch=$(mktemp /tmp/patch-pipeline-XXXXXX.patch)
    sed \
      -e "/^diff --git/s|a/$prefix/|a/|;/^diff --git/s|b/$prefix/|b/|" \
      -e "/^--- a\//s|a/$prefix/|a/|" \
      -e "/^+++ b\//s|b/$prefix/|b/|" \
      "$patch_file" > "$temp_patch"
    echo "$prefix|$temp_patch"
    return 0
  fi
  echo "|$patch_file"
}

# ============================================================================
# Validation
# ============================================================================

if [[ ! -d "$REPO_PATH" ]]; then
  die "Repo path does not exist: $REPO_PATH"
fi

STAGING_DIR="$REPO_PATH/$STAGING_PATH/$DATE"
if [[ ! -d "$STAGING_DIR" ]]; then
  die "No staged patches for $DATE at $STAGING_DIR"
fi

# Find patch files
mapfile -t PATCHES < <(find "$STAGING_DIR" -maxdepth 1 -name "*.patch" -type f | sort)
if [[ ${#PATCHES[@]} -eq 0 ]]; then
  die "No .patch files found in $STAGING_DIR"
fi

log_info "Found ${#PATCHES[@]} patch file(s)"

# ============================================================================
# Prepare repo and branch
# ============================================================================

BASE_BRANCH=$(resolve_base_branch)

# Check for clean worktree (ignore pipeline staging files)
STATUS=$(
  git_run status --porcelain --untracked-files=all | while IFS= read -r line; do
    path="${line:3}"
    if [[ "$path" == "$STAGING_PATH" || "$path" == "$STAGING_PATH/"* ]]; then
      continue
    fi
    echo "$line"
  done
)
if [[ -n "$STATUS" ]]; then
  die "Working tree is not clean. Commit or stash changes first."
fi

# Get branch name from first patch subject
FIRST_SUBJECT=$(get_patch_subject "${PATCHES[0]}")
BRANCH_SLUG=$(slugify "$FIRST_SUBJECT")
BRANCH_NAME="$REVIEW_PREFIX/$DATE/$BRANCH_SLUG"

echo "📦 Applying ${#PATCHES[@]} patch(es) to branch: $BRANCH_NAME"
echo "   Base: $BASE_BRANCH"
echo ""

ensure_local_branch "$BASE_BRANCH"
git_run checkout "$BASE_BRANCH" > /dev/null

# Create review branch
if git_run show-ref --verify --quiet "refs/heads/$BRANCH_NAME"; then
  die "Branch '$BRANCH_NAME' already exists. Delete it first: git branch -D $BRANCH_NAME"
fi

if ! git_run checkout -b "$BRANCH_NAME" 2>&1; then
  die "Could not create branch: $BRANCH_NAME"
fi

# ============================================================================
# Apply patches
# ============================================================================

APPLIED_COUNT=0
FAILED=false
FAILED_PATCH=""
FAILED_INDEX=0
FAILED_ERROR=""
FAILED_PREFIX=""
FAILED_APPLY_CHECK=""
APPLIED_TMP=$(mktemp /tmp/patch-pipeline-applied-XXXXXX.tsv)

for i in "${!PATCHES[@]}"; do
  PATCH_FILE="${PATCHES[$i]}"
  PATCH_NUM=$((i + 1))
  TOTAL=${#PATCHES[@]}
  
  SUBJECT=$(get_patch_subject "$PATCH_FILE")
  printf "  [%d/%d] Applying: %s ... " "$PATCH_NUM" "$TOTAL" "$SUBJECT"

  IFS='|' read -r STRIPPED_PREFIX APPLY_PATCH < <(prepare_patch_for_repo "$PATCH_FILE")
  if APPLY_OUTPUT=$(git_run am --3way "$APPLY_PATCH" 2>&1); then
    echo "✅"
    APPLIED_COUNT=$((APPLIED_COUNT + 1))
    commit_record=$(git_run log -1 --format='%H%x1f%s')
    commit_hash="${commit_record%%$'\x1f'*}"
    commit_subject="${commit_record#*$'\x1f'}"
    printf '%s\t%s\n' "${commit_hash:0:12}" "$commit_subject" >> "$APPLIED_TMP"
  else
    echo "❌ CONFLICT"
    FAILED=true
    FAILED_PATCH=$(basename "$PATCH_FILE")
    FAILED_INDEX=$PATCH_NUM
    FAILED_ERROR="$APPLY_OUTPUT"
    FAILED_PREFIX="$STRIPPED_PREFIX"
    if [[ -n "$STRIPPED_PREFIX" ]]; then
      if ! FAILED_APPLY_CHECK=$(git_run apply --check "$APPLY_PATCH" 2>&1); then
        :
      fi
    else
      if ! FAILED_APPLY_CHECK=$(git_run apply --check "$PATCH_FILE" 2>&1); then
        :
      fi
    fi
    [[ "$APPLY_PATCH" != "$PATCH_FILE" ]] && rm -f "$APPLY_PATCH"
    break
  fi
  [[ "$APPLY_PATCH" != "$PATCH_FILE" ]] && rm -f "$APPLY_PATCH"
done

# ============================================================================
# Report results
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"

if [[ "$FAILED" == "true" ]]; then
  log_warn "Applied $APPLIED_COUNT/$TOTAL patches (stopped at conflict on patch $FAILED_INDEX: $FAILED_PATCH)"
  if [[ -n "$FAILED_PREFIX" ]]; then
    echo "Detected repo-root prefix mismatch: stripped leading '$FAILED_PREFIX/' for diagnostics."
  fi
  if [[ -n "$FAILED_APPLY_CHECK" ]]; then
    echo "Plain apply check:"
    echo "$FAILED_APPLY_CHECK"
  fi
  echo ""
  echo "To resolve manually:"
  echo "  1. Fix conflicts in the listed files"
  echo "  2. git add <resolved-files>"
  echo "  3. git am --continue"
  echo "  Or to abort: git am --abort && git checkout $BASE_BRANCH && git branch -D $BRANCH_NAME"
else
  log_success "All ${#PATCHES[@]} patches applied successfully!"
  echo ""
  echo "Applied commits:"
  git_run log --oneline -n "$APPLIED_COUNT"
  echo ""
  echo "Review branch: $BRANCH_NAME"
fi

python3 - "$STAGING_DIR" "$BRANCH_NAME" "$BASE_BRANCH" "$TOTAL" "$FAILED" "$FAILED_PATCH" "$FAILED_INDEX" "$FAILED_ERROR" "$FAILED_PREFIX" "$FAILED_APPLY_CHECK" "$APPLIED_TMP" <<'PY'
import json
import sys
from pathlib import Path

staging = Path(sys.argv[1])
branch = sys.argv[2]
base = sys.argv[3]
total = int(sys.argv[4])
failed = sys.argv[5] == "true"
failed_patch = sys.argv[6]
failed_index = int(sys.argv[7]) if sys.argv[7] else 0
failed_error = sys.argv[8]
failed_prefix = sys.argv[9] or None
failed_apply_check = sys.argv[10]
applied_tsv = Path(sys.argv[11])

applied = []
for line in applied_tsv.read_text().splitlines():
    if not line.strip():
        continue
    hash_val, subject = line.split("\t", 1)
    applied.append({"hash": hash_val, "subject": subject})

data = {
    "branch": branch,
    "base": base,
    "applied": applied,
    "failed": None,
    "total": total,
}
if failed:
    data["failed"] = {
        "patch": failed_patch,
        "index": failed_index,
        "error": failed_error,
        "stripped_prefix": failed_prefix,
        "apply_check_error": failed_apply_check,
    }

(staging / "apply_data.json").write_text(json.dumps(data, indent=2))
PY

rm -f "$APPLIED_TMP"

if [[ "$FAILED" == "true" ]]; then
  exit 1
fi
