#!/bin/bash
# Step 5: Integrate approved patches — create PR branch and open GitHub PR
#
# Usage:
#     ./patch_integrate.sh --approval-file /path/to/approval.json
#     ./patch_integrate.sh --date 2026-03-25 --approval-file /path/to/approval.json
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
APPROVAL_FILE=""

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
    --approval-file)
      APPROVAL_FILE="$2"
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

# ============================================================================
# Validation
# ============================================================================

if [[ ! -d "$REPO_PATH" ]]; then
  die "Repo path does not exist: $REPO_PATH"
fi
if [[ ! "$DATE" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
  die "Invalid staging date '$DATE'; expected YYYY-MM-DD"
fi

STAGING_DIR="$REPO_PATH/$STAGING_PATH/$DATE"
if [[ ! -d "$STAGING_DIR" ]]; then
  die "No staging directory for $DATE"
fi
if [[ -z "$APPROVAL_FILE" ]]; then
  die "--approval-file is required; export the approval email as a scoped JSON record"
fi
if [[ ! -f "$APPROVAL_FILE" ]]; then
  die "Approval file does not exist: $APPROVAL_FILE"
fi

APPLY_DATA_FILE="$STAGING_DIR/apply_data.json"
if [[ ! -f "$APPLY_DATA_FILE" ]]; then
  die "No apply_data.json found. Run patch_apply.sh first."
fi

TEST_DATA_FILE="$STAGING_DIR/test_data.json"
REPORT_FILE="$STAGING_DIR/REVIEW_REPORT.md"
REPORT_FILE_HTML="$STAGING_DIR/REVIEW_REPORT.html"

log_info "Integrating patches from $DATE"

if ! PYTHONPATH="$SCRIPT_DIR/../python" python3 "$SCRIPT_DIR/../python/approval.py" \
    --repo "$REPO_PATH" \
    --staging "$STAGING_DIR" \
    --approval-file "$APPROVAL_FILE"; then
  die "Integration evidence validation failed"
fi

# ============================================================================
# Extract review branch from apply_data and derive integrate branch
# ============================================================================

REVIEW_BRANCH=$(grep -oP '"branch":\s*"\K[^"]+' "$APPLY_DATA_FILE" || echo "")
if [[ -z "$REVIEW_BRANCH" ]]; then
  die "Could not determine review branch from apply_data.json"
fi

# Derive integrate branch: review/<date>/<slug> → integrate/<date>/<slug>
BASE_BRANCH=$(grep -oP '"base":\s*"\K[^"]+' "$APPLY_DATA_FILE" || echo "$WORKING_BRANCH")
WORKING_BRANCH="${BASE_BRANCH:-$WORKING_BRANCH}"
BRANCH_SUFFIX="${REVIEW_BRANCH#*/}"  # strip first segment (e.g. "review")
INTEGRATE_BRANCH="${INTEGRATE_BRANCH_PREFIX}/${BRANCH_SUFFIX}"
BASE_COMMIT=$(grep -oP '"base_commit":\s*"\K[^"]+' "$STAGING_DIR/approval_data.json" | tail -1 || echo "")
APPROVAL_SENDER=$(grep -oP '"sender":\s*"\K[^"]+' "$STAGING_DIR/approval_data.json" | head -1 || echo "")
APPROVAL_MESSAGE_ID=$(grep -oP '"message_id":\s*"\K[^"]+' "$STAGING_DIR/approval_data.json" | head -1 || echo "")

log_info "Review branch:    $REVIEW_BRANCH"
log_info "Integrate branch: $INTEGRATE_BRANCH"
log_info "Target branch:    $WORKING_BRANCH"
log_info "Approval:         $APPROVAL_SENDER / $APPROVAL_MESSAGE_ID"

if ! git_run show-ref --verify --quiet "refs/heads/$REVIEW_BRANCH"; then
  die "Review branch does not exist: $REVIEW_BRANCH"
fi

if [[ -f "$REPORT_FILE_HTML" ]]; then
  log_info "HTML report: $REPORT_FILE_HTML"
fi
if [[ -f "$REPORT_FILE" ]]; then
  log_info "Markdown report: $REPORT_FILE"
fi

# ============================================================================
# Ensure clean worktree
# ============================================================================

echo ""
STATUS=$(git_run status --porcelain --untracked-files=all | awk -v ignored="$STAGING_PATH" '{ path = substr($0, 4); if (path != ignored && index(path, ignored "/") != 1) print }')
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

# Get every commit unique to the reviewed branch, including cleanup commits.
if [[ -z "$BASE_COMMIT" ]]; then
  die "Approval verification did not record the review base commit"
fi
COMMITS=$(git_run rev-list --reverse --first-parent "$BASE_COMMIT..$REVIEW_BRANCH")

if [[ -z "$COMMITS" ]]; then
  die "No reviewed commits to cherry-pick"
fi

while IFS= read -r COMMIT_HASH; do
  [[ -z "$COMMIT_HASH" ]] && continue
  printf "  Cherry-picking %s ... " "$COMMIT_HASH"
  PARENT_COUNT=$(git_run rev-list --parents -n 1 "$COMMIT_HASH" | awk '{print NF - 1}')
  CHERRY_PICK_ARGS=("$COMMIT_HASH")
  if [[ "$PARENT_COUNT" -gt 1 ]]; then
    CHERRY_PICK_ARGS=(-m 1 "$COMMIT_HASH")
  fi
  if git_run cherry-pick "${CHERRY_PICK_ARGS[@]}" > /dev/null 2>&1; then
    echo "✅"
  else
    echo "❌"
    log_warn "Cherry-pick conflict on $COMMIT_HASH"
    git_run cherry-pick --abort 2>/dev/null || true
    git_run checkout "$ORIGINAL_BRANCH" 2>/dev/null || true
    git_run branch -D "$INTEGRATE_BRANCH" 2>/dev/null || true
    die "Cherry-pick aborted and integrate branch cleaned up"
  fi
done <<< "$COMMITS"

log_success "All reviewed commits cherry-picked to $INTEGRATE_BRANCH"

# ============================================================================
# Push integrate branch to origin
# ============================================================================

echo ""
log_info "Pushing $INTEGRATE_BRANCH to origin..."
if git_run push origin "$INTEGRATE_BRANCH"; then
  log_success "Branch pushed."
else
  die "Push failed. Push manually: git push origin $INTEGRATE_BRANCH"
fi

# ============================================================================
# Create GitHub PR via gh CLI
# ============================================================================

echo ""
log_info "Creating GitHub PR ($INTEGRATE_BRANCH → $WORKING_BRANCH)..."

PR_TITLE="Integrate: $(git_run log -1 --format="%s" "$INTEGRATE_BRANCH")"
PR_BODY="Integrated patches via patch-pipeline.

Review branch: $REVIEW_BRANCH
Integrate branch: $INTEGRATE_BRANCH
Approval sender: $APPROVAL_SENDER
Approval message ID: $APPROVAL_MESSAGE_ID"

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
python3 - "$INTEGRATE_DATA_FILE" "$REVIEW_BRANCH" "$INTEGRATE_BRANCH" "$WORKING_BRANCH" "$PR_URL" "$APPROVAL_SENDER" "$APPROVAL_MESSAGE_ID" <<'PYJSON'
import json
import sys
from pathlib import Path

output, review_branch, integrate_branch, base_branch, pr_url, sender, message_id = sys.argv[1:]
data = {
    "review_branch": review_branch,
    "integrate_branch": integrate_branch,
    "base_branch": base_branch,
    "pr_url": pr_url,
    "approval": {"sender": sender, "message_id": message_id},
}
Path(output).write_text(json.dumps(data, indent=2) + "\n")
PYJSON
log_info "Integrate data saved to $INTEGRATE_DATA_FILE"

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"
if [[ -n "$PR_URL" ]]; then
  log_success "Integration complete; PR created."
  echo "   PR: $PR_URL"
else
  log_warn "Integration branch ready; PR creation is pending."
fi
echo "   Branch: $INTEGRATE_BRANCH"
echo "   Target: $WORKING_BRANCH"
