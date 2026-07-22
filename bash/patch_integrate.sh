#!/bin/bash
# Step 5: Integrate approved patches — create PR branch and open GitHub PR
#
# Usage:
#     ./patch_integrate.sh                   # integrate today's patches
#     ./patch_integrate.sh --date 2026-03-25 # integrate specific date
#
# Creates an integrate/<date>/<slug> branch, cherry-picks commits from the
# review branch, pushes to origin, and opens a GitHub PR via the gh CLI.

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_PATH="${REPO_PATH:-.}"
DATE="${DATE:-$(date +%Y-%m-%d)}"
STAGING_PATH="${STAGING_PATH:-.patch-staging}"
WORKING_BRANCH="${PATCH_PIPELINE_WORKING_BRANCH:-main}"
INTEGRATE_BRANCH_PREFIX="${PATCH_PIPELINE_INTEGRATE_BRANCH_PREFIX:-integrate}"

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
REPORT_FILE_HTML="$STAGING_DIR/REVIEW_REPORT.html"

log_info "Integrating patches from $DATE"

# ============================================================================
# Extract review branch from apply_data and derive integrate branch
# ============================================================================

REVIEW_BRANCH=$(grep -oP '"branch":\s*"\K[^"]+' "$APPLY_DATA_FILE" || echo "")
if [[ -z "$REVIEW_BRANCH" ]]; then
  die "Could not determine review branch from apply_data.json"
fi

# Derive integrate branch: review/<date>/<slug> → integrate/<date>/<slug>
BRANCH_SUFFIX="${REVIEW_BRANCH#*/}"  # strip first segment (e.g. "review")
INTEGRATE_BRANCH="${INTEGRATE_BRANCH_PREFIX}/${BRANCH_SUFFIX}"

log_info "Review branch:    $REVIEW_BRANCH"
log_info "Integrate branch: $INTEGRATE_BRANCH"
log_info "Target branch:    $WORKING_BRANCH"

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

if [[ -f "$REPORT_FILE_HTML" ]]; then
  log_info "HTML report (open this for review): $REPORT_FILE_HTML"
fi

if [[ -f "$REPORT_FILE" ]]; then
  log_info "Review report available at: $REPORT_FILE"
  echo ""
  if grep -qi -- '- \[x\].*\*\*LGTM\*\*' "$REPORT_FILE" 2>/dev/null; then
    log_success "Report shows LGTM approval"
  else
    log_warn "Report exists but LGTM status not explicitly marked"
  fi
else
  log_warn "No review report found at $REPORT_FILE"
fi

echo ""
echo "Has the sender blessed these changes? (yes/no)"
read -p "Enter confirmation [no]: " -r blessed
blessed=$(echo "$blessed" | tr '[:upper:]' '[:lower:]')

if [[ "$blessed" != "yes" && "$blessed" != "y" ]]; then
  log_warn "Sender blessing required before integration. Aborted."
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
# Create integrate branch from working branch and cherry-pick commits
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"
echo "🚀 Integration in Progress"
echo "────────────────────────────────────────────────────────────"
echo ""

log_info "Checking out $WORKING_BRANCH"
ORIGINAL_BRANCH=$(git_run rev-parse --abbrev-ref HEAD)
if ! git_run checkout "$WORKING_BRANCH"; then
  die "Could not checkout $WORKING_BRANCH"
fi

log_info "Creating integrate branch: $INTEGRATE_BRANCH"
if git_run show-ref --verify --quiet "refs/heads/$INTEGRATE_BRANCH" 2>/dev/null; then
  die "Branch '$INTEGRATE_BRANCH' already exists. Delete it first: git branch -D $INTEGRATE_BRANCH"
fi
git_run checkout -b "$INTEGRATE_BRANCH"

# Get commits from review branch
REVIEW_BASE=$(git_run merge-base "$WORKING_BRANCH" "$REVIEW_BRANCH")
COMMITS=$(git_run log --oneline --reverse "$REVIEW_BASE..$REVIEW_BRANCH")

if [[ -z "$COMMITS" ]]; then
  log_warn "No new commits to cherry-pick"
  exit 0
fi

CHERRY_PICK_FAILED=false
while IFS= read -r line; do
  COMMIT_HASH=$(echo "$line" | awk '{print $1}')

  printf "  Cherry-picking %s ... " "$COMMIT_HASH"
  if git_run cherry-pick "$COMMIT_HASH" > /dev/null 2>&1; then
    echo "✅"
  else
    echo "❌"
    log_warn "Cherry-pick conflict on $COMMIT_HASH"
    echo ""
    echo "To resolve:"
    echo "  1. Fix conflicts in listed files"
    echo "  2. git add <files>"
    echo "  3. git cherry-pick --continue"
    echo ""
    read -p "Abort cherry-pick and clean up integrate branch? (Y/n): " -r abort_choice
    abort_choice=$(echo "${abort_choice:-y}" | tr '[:upper:]' '[:lower:]')
    if [[ "$abort_choice" != "n" ]]; then
      git_run cherry-pick --abort 2>/dev/null || true
      git_run checkout "$ORIGINAL_BRANCH" 2>/dev/null || true
      git_run branch -D "$INTEGRATE_BRANCH" 2>/dev/null || true
      log_warn "Cherry-pick aborted and integrate branch cleaned up."
    fi
    CHERRY_PICK_FAILED=true
    break
  fi
done < <(echo "$COMMITS")

if [[ "$CHERRY_PICK_FAILED" == "true" ]]; then
  log_warn "Integration incomplete due to cherry-pick conflict"
  exit 1
fi

log_success "All commits cherry-picked to $INTEGRATE_BRANCH"

# ============================================================================
# Push integrate branch to origin
# ============================================================================

echo ""
log_info "Pushing $INTEGRATE_BRANCH to origin..."
if git_run push origin "$INTEGRATE_BRANCH"; then
  log_success "Branch pushed."
else
  log_warn "Push failed. Push manually: git push origin $INTEGRATE_BRANCH"
fi

# ============================================================================
# Create GitHub PR via gh CLI
# ============================================================================

echo ""
log_info "Creating GitHub PR ($INTEGRATE_BRANCH → $WORKING_BRANCH)..."

PR_TITLE="Integrate: $(git_run log -1 --format="%s" "$INTEGRATE_BRANCH")"
PR_BODY="Integrated patches via patch-pipeline.

Review branch: $REVIEW_BRANCH
Integrate branch: $INTEGRATE_BRANCH"

PR_URL=""
if command -v gh &> /dev/null; then
  if PR_URL=$(gh pr create \
      --base "$WORKING_BRANCH" \
      --head "$INTEGRATE_BRANCH" \
      --title "$PR_TITLE" \
      --body "$PR_BODY" 2>&1); then
    log_success "PR created: $PR_URL"
  else
    log_warn "gh pr create failed. Create the PR manually:"
    echo "   gh pr create --base $WORKING_BRANCH --head $INTEGRATE_BRANCH"
    PR_URL=""
  fi
else
  log_warn "gh CLI not found. Create the PR manually:"
  echo "   gh pr create --base $WORKING_BRANCH --head $INTEGRATE_BRANCH"
fi

# ============================================================================
# Save integrate data
# ============================================================================

INTEGRATE_DATA_FILE="$STAGING_DIR/integrate_data.json"
cat > "$INTEGRATE_DATA_FILE" << EOF
{
  "review_branch": "$REVIEW_BRANCH",
  "integrate_branch": "$INTEGRATE_BRANCH",
  "base_branch": "$WORKING_BRANCH",
  "pr_url": "$PR_URL"
}
EOF
log_info "Integrate data saved to $INTEGRATE_DATA_FILE"

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"
log_success "Integration complete!"
[[ -n "$PR_URL" ]] && echo "   PR: $PR_URL"
echo "   Branch: $INTEGRATE_BRANCH"
echo "   Target: $WORKING_BRANCH"
