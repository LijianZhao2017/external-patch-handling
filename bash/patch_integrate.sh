#!/bin/bash
# Step 5: Integrate approved patches to working branch (bash version)
#
# Usage:
#     ./patch_integrate.sh                   # integrate today's patches
#     ./patch_integrate.sh --date 2026-03-25 # integrate specific date
#
# This script cherry-picks commits from the review branch to the working branch
# after verifying sender approval.

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_PATH="${REPO_PATH:-.}"
DATE="${DATE:-$(date +%Y-%m-%d)}"
STAGING_PATH="${STAGING_PATH:-.patch-staging}"
WORKING_BRANCH="${PATCH_PIPELINE_WORKING_BRANCH:-main}"

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
    --force)
      FORCE_FLAG=true
      shift
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

# ============================================================================
# Validation
# ============================================================================

if [[ ! -d "$REPO_PATH" ]]; then
  die "Repo path does not exist: $REPO_PATH"
fi

STAGING_DIR="$REPO_PATH/$STAGING_PATH/$DATE"
if [[ ! -d "$STAGING_DIR" ]]; then
  die "No staging directory for $DATE"
fi

APPLY_DATA_FILE="$STAGING_DIR/apply_data.json"
if [[ ! -f "$APPLY_DATA_FILE" ]]; then
  die "No apply_data.json found. Run patch_apply.sh first."
fi

TEST_DATA_FILE="$STAGING_DIR/test_data.json"
if [[ ! -f "$TEST_DATA_FILE" ]]; then
  log_warn "No test_data.json found. Tests may not have been run."
fi

REPORT_FILE="$STAGING_DIR/REVIEW_REPORT.md"

log_info "Integrating patches from $DATE"

# ============================================================================
# Extract review branch from apply_data
# ============================================================================

REVIEW_BRANCH=$(grep -oP '"branch":\s*"\K[^"]+' "$APPLY_DATA_FILE" || echo "")
if [[ -z "$REVIEW_BRANCH" ]]; then
  die "Could not determine review branch from apply_data.json"
fi

log_info "Review branch: $REVIEW_BRANCH"

if ! git_run show-ref --verify --quiet "refs/heads/$REVIEW_BRANCH"; then
  die "Review branch does not exist: $REVIEW_BRANCH"
fi

# ============================================================================
# Approval Check
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"
echo "📋 Integration Approval Check"
echo "────────────────────────────────────────────────────────────"
echo ""

if [[ -f "$REPORT_FILE" ]]; then
  log_info "Review report available at: $REPORT_FILE"
  echo ""
  # Show LGTM status if available
  if grep -q "LGTM.*✅" "$REPORT_FILE" 2>/dev/null; then
    log_success "Report shows LGTM approval"
  else
    log_warn "Report exists but LGTM status not explicitly marked"
  fi
else
  log_warn "No review report found at $REPORT_FILE"
fi

echo ""
echo "Proceed with integration to $WORKING_BRANCH? (yes/no)"
read -p "Enter confirmation [no]: " -r confirm
confirm=$(echo "$confirm" | tr '[:lower:]' '[:upper:]')

if [[ "$confirm" != "YES" && "$confirm" != "Y" ]]; then
  log_warn "Integration cancelled"
  exit 0
fi

# ============================================================================
# Ensure clean worktree
# ============================================================================

echo ""
STATUS=$(git_run status --porcelain | grep -v "^?" || echo "")
if [[ -n "$STATUS" ]]; then
  die "Working tree is not clean. Commit or stash changes first."
fi

# ============================================================================
# Checkout working branch and cherry-pick commits
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"
echo "🚀 Integration in Progress"
echo "────────────────────────────────────────────────────────────"
echo ""

log_info "Checking out $WORKING_BRANCH"
if ! git_run checkout "$WORKING_BRANCH"; then
  die "Could not checkout $WORKING_BRANCH"
fi

# Get commits from review branch
log_info "Cherry-picking commits from $REVIEW_BRANCH"

# Get range of commits on review branch
REVIEW_BASE=$(git_run merge-base "$WORKING_BRANCH" "$REVIEW_BRANCH")
COMMITS=$(git_run log --oneline "$REVIEW_BASE..$REVIEW_BRANCH")

if [[ -z "$COMMITS" ]]; then
  log_warn "No new commits to cherry-pick"
  exit 0
fi

# Cherry-pick each commit
CHERRY_PICK_FAILED=false
while IFS= read -r line; do
  COMMIT_HASH=$(echo "$line" | awk '{print $1}')
  COMMIT_MSG=$(echo "$line" | cut -d' ' -f2-)
  
  printf "  Cherry-picking %s ... " "$COMMIT_HASH"
  if git_run cherry-pick "$COMMIT_HASH" > /dev/null 2>&1; then
    echo "✅"
  else
    echo "❌"
    CHERRY_PICK_FAILED=true
    log_warn "Cherry-pick conflict on $COMMIT_HASH"
    echo ""
    echo "To resolve:"
    echo "  1. Fix conflicts in listed files"
    echo "  2. git add <files>"
    echo "  3. git cherry-pick --continue"
    echo "  Or abort: git cherry-pick --abort"
    break
  fi
done < <(echo "$COMMITS")

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"

if [[ "$CHERRY_PICK_FAILED" == "false" ]]; then
  log_success "All commits integrated to $WORKING_BRANCH"
  echo ""
  log_info "Next steps:"
  echo "  1. Verify the integrated changes with: git log --oneline -n 10"
  echo "  2. Run final validation tests if needed"
  echo "  3. Push to remote: git push origin $WORKING_BRANCH"
else
  log_warn "Integration incomplete due to cherry-pick conflict"
  exit 1
fi
