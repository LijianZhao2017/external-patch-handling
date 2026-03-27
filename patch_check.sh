#!/bin/bash
# Step 3: Functional Equivalence Check (bash version) — CRITICAL STEP
#
# Usage:
#     ./patch_check.sh                       # check today's patches
#     ./patch_check.sh --date 2026-03-25     # check specific date
#
# Compares what the sender INTENDED (their patch) vs what ACTUALLY LANDED
# on the receiver side (git diff main..review-branch).

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
    --verbose)
      VERBOSE=true
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

VERBOSE="${VERBOSE:-false}"

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

# Count insertions/deletions in a diff for a specific file
get_diff_stats() {
  local diff_output="$1"
  local filename="$2"
  
  # Extract lines for this file, count + and - lines
  local insertions=0
  local deletions=0
  
  insertions=$(echo "$diff_output" | grep "^+" | grep -v "^+++" | grep -c . || echo 0)
  deletions=$(echo "$diff_output" | grep "^-" | grep -v "^---" | grep -c . || echo 0)
  
  echo "$insertions:$deletions"
}

# Calculate similarity percentage
calc_similarity() {
  local sent_adds=$1
  local sent_dels=$2
  local recv_adds=$3
  local recv_dels=$4
  
  local total_sent=$((sent_adds + sent_dels))
  local total_recv=$((recv_adds + recv_dels))
  
  # Both empty = 100% match
  if [[ $total_sent -eq 0 && $total_recv -eq 0 ]]; then
    echo 100
    return
  fi
  
  # One empty, other not = 0% match
  if [[ $total_sent -eq 0 || $total_recv -eq 0 ]]; then
    echo 0
    return
  fi
  
  # Calculate overlap: what percentage of sender changes are present in receiver
  # Simple metric: min adds and dels as percentage of sent
  local matched=0
  if [[ $sent_adds -gt 0 ]]; then
    matched=$((recv_adds * 100 / sent_adds))
  fi
  if [[ $sent_dels -gt 0 ]]; then
    matched=$(((matched + recv_dels * 100 / sent_dels) / 2))
  fi
  
  echo "$matched"
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

# ============================================================================
# Extract review branch and get patches
# ============================================================================

REVIEW_BRANCH=$(grep -oP '"branch":\s*"\K[^"]+' "$APPLY_DATA_FILE")
if [[ -z "$REVIEW_BRANCH" ]]; then
  die "Could not extract review branch from apply_data.json"
fi
log_info "Checking equivalence for $REVIEW_BRANCH"

PATCHES=($(find "$STAGING_DIR" -maxdepth 1 -name "*.patch" -type f | sort))
if [[ ${#PATCHES[@]} -eq 0 ]]; then
  die "No .patch files found in $STAGING_DIR"
fi

echo ""
echo "────────────────────────────────────────────────────────────"
echo "📊 Functional Equivalence Check"
echo "────────────────────────────────────────────────────────────"
echo ""

# ============================================================================
# Build map of sender intent (patches) vs receiver reality (git diff)
# ============================================================================

declare -A PATCH_FILES
declare -A PATCH_ADDS
declare -A PATCH_DELS

# Parse what sender intended to change
for patch_file in "${PATCHES[@]}"; do
  while IFS= read -r file; do
    if [[ -n "$file" ]]; then
      PATCH_FILES["$file"]=1
    fi
  done < <(grep "^diff --git" "$patch_file" | sed 's|^diff --git a/||; s| b/.*||')
  
  # Count sender's adds/dels per file using awk
  while IFS=':' read -r file adds dels; do
    if [[ -n "$file" ]]; then
      PATCH_ADDS["$file"]=$((${PATCH_ADDS["$file"]:-0} + adds))
      PATCH_DELS["$file"]=$((${PATCH_DELS["$file"]:-0} + dels))
    fi
  done < <(
    awk '
      /^diff --git a\// {
        if (file != "") print file ":" adds ":" dels
        file=$4; gsub(/^a\//, "", file); gsub(/ b\/.*/, "", file)
        adds=0; dels=0
        next
      }
      /^+[^+]/ && file != "" { adds++ }
      /^-[^-]/ && file != "" { dels++ }
      END { if (file != "") print file ":" adds ":" dels }
    ' "$patch_file"
  )
done

# Get receiver's actual changes
RECV_DIFF=$(git_run diff "$WORKING_BRANCH..$REVIEW_BRANCH" || echo "")

declare -A RECV_ADDS
declare -A RECV_DELS

while IFS=':' read -r file adds dels; do
  if [[ -n "$file" ]]; then
    RECV_ADDS["$file"]=$adds
    RECV_DELS["$file"]=$dels
  fi
done < <(
  echo "$RECV_DIFF" | awk '
    /^diff --git a\// {
      if (file != "") {
        print file ":" adds ":" dels
      }
      file=$4; gsub(/^a\//, "", file); gsub(/ b\/.*/, "", file)
      adds=0; dels=0
      next
    }
    /^+[^+]/ { adds++ }
    /^-[^-]/ { dels++ }
    END { if (file != "") print file ":" adds ":" dels }
  '
)

# ============================================================================
# Compare and report
# ============================================================================

echo "| Status | File | Sent +/- | Recv +/- | Match |"
echo "|--------|------|----------|----------|-------|"

RESULTS=()
MATCH_COUNT=0
PARTIAL_COUNT=0
MISMATCH_COUNT=0
MISSING_COUNT=0
EXTRA_COUNT=0

# Check all files sender touched
for file in "${!PATCH_FILES[@]}"; do
  sent_adds=${PATCH_ADDS["$file"]:-0}
  sent_dels=${PATCH_DELS["$file"]:-0}
  recv_adds=${RECV_ADDS["$file"]:-0}
  recv_dels=${RECV_DELS["$file"]:-0}
  
  if [[ $recv_adds -eq 0 && $recv_dels -eq 0 ]]; then
    # File sender touched but nothing landed
    echo "| MISSING | $file | +$sent_adds/-$sent_dels | +0/-0 | 0% |"
    MISSING_COUNT=$((MISSING_COUNT + 1))
    RESULTS+=("MISSING:$file")
  else
    # Calculate similarity
    similarity=$(calc_similarity "$sent_adds" "$sent_dels" "$recv_adds" "$recv_dels")
    
    if [[ $similarity -ge 75 ]]; then
      echo "| MATCH   | $file | +$sent_adds/-$sent_dels | +$recv_adds/-$recv_dels | ${similarity}% |"
      MATCH_COUNT=$((MATCH_COUNT + 1))
      RESULTS+=("MATCH:$file")
    elif [[ $similarity -ge 40 ]]; then
      echo "| PARTIAL | $file | +$sent_adds/-$sent_dels | +$recv_adds/-$recv_dels | ${similarity}% |"
      PARTIAL_COUNT=$((PARTIAL_COUNT + 1))
      RESULTS+=("PARTIAL:$file")
    else
      echo "| MISMATCH| $file | +$sent_adds/-$sent_dels | +$recv_adds/-$recv_dels | ${similarity}% |"
      MISMATCH_COUNT=$((MISMATCH_COUNT + 1))
      RESULTS+=("MISMATCH:$file")
    fi
  fi
done

# Check for receiver changes sender didn't touch
for file in "${!RECV_ADDS[@]}"; do
  if [[ ! -v PATCH_FILES["$file"] ]]; then
    recv_adds=${RECV_ADDS["$file"]}
    recv_dels=${RECV_DELS["$file"]}
    echo "| EXTRA   | $file | +0/-0 | +$recv_adds/-$recv_dels | N/A |"
    EXTRA_COUNT=$((EXTRA_COUNT + 1))
    RESULTS+=("EXTRA:$file")
  fi
done

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"
echo "Summary: MATCH=$MATCH_COUNT  PARTIAL=$PARTIAL_COUNT  MISMATCH=$MISMATCH_COUNT  MISSING=$MISSING_COUNT  EXTRA=$EXTRA_COUNT"

if [[ $MATCH_COUNT -eq ${#PATCH_FILES[@]} && $EXTRA_COUNT -eq 0 ]]; then
  log_success "All patches functionally equivalent"
elif [[ $MISMATCH_COUNT -eq 0 && $MISSING_COUNT -eq 0 ]]; then
  log_warn "Patches applied with partial matches or receiver adaptations — review recommended"
else
  log_warn "Significant divergence detected — confirm intent with sender"
fi

# Save check data for report
CHECK_DATA=$(cat <<EOF
{
  "date": "$DATE",
  "review_branch": "$REVIEW_BRANCH",
  "match": $MATCH_COUNT,
  "partial": $PARTIAL_COUNT,
  "mismatch": $MISMATCH_COUNT,
  "missing": $MISSING_COUNT,
  "extra": $EXTRA_COUNT,
  "total_files_touched": ${#PATCH_FILES[@]},
  "results": [$(printf '"%s",' "${RESULTS[@]}" | sed 's/,$//')]
}
EOF
)

echo "$CHECK_DATA" | tee "$STAGING_DIR/check_data.json" > /dev/null
log_info "Check data saved to $STAGING_DIR/check_data.json"
