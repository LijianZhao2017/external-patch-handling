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
  echo "$1" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9]*/-/g' | sed 's/^-*//; s/-*$//' | cut -c1-50
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
PATCHES=($(find "$STAGING_DIR" -maxdepth 1 -name "*.patch" -type f | sort))
if [[ ${#PATCHES[@]} -eq 0 ]]; then
  die "No .patch files found in $STAGING_DIR"
fi

log_info "Found ${#PATCHES[@]} patch file(s)"

# ============================================================================
# Prepare repo and branch
# ============================================================================

# Check for clean worktree (ignore untracked files, only modified tracked)
STATUS=$(git_run status --porcelain | grep -v "^?" || echo "")
if [[ -n "$STATUS" ]]; then
  die "Working tree is not clean. Commit or stash changes first."
fi

# Get branch name from first patch subject
FIRST_SUBJECT=$(get_patch_subject "${PATCHES[0]}")
BRANCH_SLUG=$(slugify "$FIRST_SUBJECT")
BRANCH_NAME="$REVIEW_PREFIX/$DATE/$BRANCH_SLUG"

echo "📦 Applying ${#PATCHES[@]} patch(es) to branch: $BRANCH_NAME"
echo "   Base: $WORKING_BRANCH"
echo ""

# Checkout working branch (non-fatal if it doesn't exist)
if git_run show-ref --verify --quiet "refs/heads/$WORKING_BRANCH"; then
  git_run checkout "$WORKING_BRANCH" 2>/dev/null || true
fi

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

for i in "${!PATCHES[@]}"; do
  PATCH_FILE="${PATCHES[$i]}"
  PATCH_NUM=$((i + 1))
  TOTAL=${#PATCHES[@]}
  
  SUBJECT=$(get_patch_subject "$PATCH_FILE")
  printf "  [%d/%d] Applying: %s ... " "$PATCH_NUM" "$TOTAL" "$SUBJECT"
  
  if git_run am --3way "$PATCH_FILE" > /dev/null 2>&1; then
    echo "✅"
    APPLIED_COUNT=$((APPLIED_COUNT + 1))
  else
    echo "❌ CONFLICT"
    FAILED=true
    FAILED_PATCH=$(basename "$PATCH_FILE")
    FAILED_INDEX=$PATCH_NUM
    break
  fi
done

# ============================================================================
# Report results
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"

if [[ "$FAILED" == "true" ]]; then
  log_warn "Applied $APPLIED_COUNT/$TOTAL patches (stopped at conflict on patch $FAILED_INDEX: $FAILED_PATCH)"
  echo ""
  echo "To resolve manually:"
  echo "  1. Fix conflicts in the listed files"
  echo "  2. git add <resolved-files>"
  echo "  3. git am --continue"
  echo "  Or to abort: git am --abort && git checkout $WORKING_BRANCH && git branch -D $BRANCH_NAME"
  exit 1
else
  log_success "All ${#PATCHES[@]} patches applied successfully!"
  echo ""
  echo "Applied commits:"
  git_run log --oneline -n "$APPLIED_COUNT"
  echo ""
  echo "Review branch: $BRANCH_NAME"
fi
