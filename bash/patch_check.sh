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

# Calculate a bounded similarity percentage for the change categories present.
calc_similarity() {
  local sent_adds=$1
  local sent_dels=$2
  local recv_adds=$3
  local recv_dels=$4
  local add_score=-1
  local del_score=-1

  if [[ $sent_adds -gt 0 || $recv_adds -gt 0 ]]; then
    if [[ $sent_adds -eq 0 || $recv_adds -eq 0 ]]; then
      add_score=0
    else
      local add_max=$((sent_adds > recv_adds ? sent_adds : recv_adds))
      local add_min=$((sent_adds < recv_adds ? sent_adds : recv_adds))
      add_score=$((add_min * 100 / add_max))
    fi
  fi
  if [[ $sent_dels -gt 0 || $recv_dels -gt 0 ]]; then
    if [[ $sent_dels -eq 0 || $recv_dels -eq 0 ]]; then
      del_score=0
    else
      local del_max=$((sent_dels > recv_dels ? sent_dels : recv_dels))
      local del_min=$((sent_dels < recv_dels ? sent_dels : recv_dels))
      del_score=$((del_min * 100 / del_max))
    fi
  fi

  if [[ $add_score -lt 0 && $del_score -lt 0 ]]; then
    echo 100
  elif [[ $add_score -lt 0 ]]; then
    echo "$del_score"
  elif [[ $del_score -lt 0 ]]; then
    echo "$add_score"
  else
    echo $(((add_score + del_score) / 2))
  fi
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

APPLY_DATA_FILE="$STAGING_DIR/apply_data.json"
if [[ ! -f "$APPLY_DATA_FILE" ]]; then
  die "No apply_data.json found. Run patch_apply.sh first."
fi

# ============================================================================
# Extract review branch and get patches
# ============================================================================

REVIEW_BRANCH=$(grep -oP '"branch":\s*"\K[^"]+' "$APPLY_DATA_FILE")
BASE_BRANCH=$(grep -oP '"base":\s*"\K[^"]+' "$APPLY_DATA_FILE" || true)
BASE_BRANCH="${BASE_BRANCH:-$WORKING_BRANCH}"
if [[ -z "$REVIEW_BRANCH" ]]; then
  die "Could not extract review branch from apply_data.json"
fi
log_info "Checking equivalence for $REVIEW_BRANCH against $BASE_BRANCH"

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

# Detect repo-root prefix from sender patch paths (e.g. "Intel/Pkg/foo.c" → "Pkg/foo.c")
REPO_NAME=$(basename "$REPO_PATH")
STRIP_PREFIX=""
_all_match=true
for patch_file in "${PATCHES[@]}"; do
  while IFS= read -r file; do
    if [[ -n "$file" ]]; then
      if [[ "$file" == "$REPO_NAME/"* ]]; then
        stripped="${file#"$REPO_NAME/"}"
        if [[ -e "$REPO_PATH/$file" || ! -e "$REPO_PATH/$stripped" ]]; then
          _all_match=false
          break
        fi
      else
        _all_match=false
        break
      fi
    fi
  done < <(grep "^diff --git" "$patch_file" | sed 's|^diff --git a/||; s| b/.*||')
  $_all_match || break
done
if $_all_match; then
  STRIP_PREFIX="$REPO_NAME"
fi

declare -A PATCH_FILES
declare -A PATCH_ADDS
declare -A PATCH_DELS

# Parse what sender intended to change
for patch_file in "${PATCHES[@]}"; do
  while IFS= read -r file; do
    if [[ -n "$file" ]]; then
      [[ -n "$STRIP_PREFIX" && "$file" == "$STRIP_PREFIX/"* ]] && file="${file#"$STRIP_PREFIX/"}"
      PATCH_FILES["$file"]=1
    fi
  done < <(grep "^diff --git" "$patch_file" | sed 's|^diff --git a/||; s| b/.*||')
  
  # Count sender's adds/dels per file using awk
  while IFS=':' read -r file adds dels; do
    if [[ -n "$file" ]]; then
      [[ -n "$STRIP_PREFIX" && "$file" == "$STRIP_PREFIX/"* ]] && file="${file#"$STRIP_PREFIX/"}"
      PATCH_ADDS["$file"]=$((${PATCH_ADDS["$file"]:-0} + adds))
      PATCH_DELS["$file"]=$((${PATCH_DELS["$file"]:-0} + dels))
    fi
  done < <(
    awk '
      /^diff --git a\// {
        if (file != "") print file ":" adds ":" dels
        file=$3; gsub(/^a\//, "", file); gsub(/ b\/.*/, "", file)
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
RECV_DIFF=$(git_run diff "$BASE_BRANCH..$REVIEW_BRANCH" || echo "")

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
      file=$3; gsub(/^a\//, "", file); gsub(/ b\/.*/, "", file)
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
CHECK_RESULTS_FILE=$(mktemp /tmp/patch-pipeline-check-XXXXXX.tsv)
trap 'rm -f "$CHECK_RESULTS_FILE"' EXIT
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
    printf '%s\tMISSING\t0\t%s\t0\t%s\t0\n' "$file" "$sent_adds" "$sent_dels" >> "$CHECK_RESULTS_FILE"
  else
    # Calculate similarity
    similarity=$(calc_similarity "$sent_adds" "$sent_dels" "$recv_adds" "$recv_dels")
    status="MISMATCH"
    if [[ $similarity -ge 75 ]]; then
      status="MATCH"
      MATCH_COUNT=$((MATCH_COUNT + 1))
    elif [[ $similarity -ge 40 ]]; then
      status="PARTIAL"
      PARTIAL_COUNT=$((PARTIAL_COUNT + 1))
    else
      MISMATCH_COUNT=$((MISMATCH_COUNT + 1))
    fi
    printf '| %-7s | %s | +%s/-%s | +%s/-%s | %s%% |\n' "$status" "$file" "$sent_adds" "$sent_dels" "$recv_adds" "$recv_dels" "$similarity"
    RESULTS+=("$status:$file")
    printf '%s\t%s\t%s\t%s\t%s\t%s\t%s\n' "$file" "$status" "$similarity" "$sent_adds" "$recv_adds" "$sent_dels" "$recv_dels" >> "$CHECK_RESULTS_FILE"
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
    printf '%s\tEXTRA\t0\t0\t%s\t0\t%s\n' "$file" "$recv_adds" "$recv_dels" >> "$CHECK_RESULTS_FILE"
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

# Save the same structured schema emitted by the Python implementation.
python3 - "$STAGING_DIR" "$DATE" "$REVIEW_BRANCH" "$BASE_BRANCH" "$MATCH_COUNT" "$PARTIAL_COUNT" "$MISMATCH_COUNT" "$MISSING_COUNT" "$EXTRA_COUNT" "$CHECK_RESULTS_FILE" <<'PYJSON'
import json
import sys
from pathlib import Path

staging = Path(sys.argv[1])
date, review_branch, base_branch = sys.argv[2:5]
counts = [int(value) for value in sys.argv[5:10]]
results_file = Path(sys.argv[10])
files = []
for line in results_file.read_text().splitlines():
    filename, status, similarity, sender_added, receiver_added, sender_removed, receiver_removed = line.split("\t")
    files.append({
        "file": filename,
        "status": status,
        "similarity": int(similarity) / 100,
        "sender_added": int(sender_added),
        "receiver_added": int(receiver_added),
        "sender_removed": int(sender_removed),
        "receiver_removed": int(receiver_removed),
        "functions": [],
    })
match, partial, mismatch, missing, extra = counts
data = {
    "date": date,
    "review_branch": review_branch,
    "base_branch": base_branch,
    "files": files,
    "overall": "PASS" if partial == mismatch == missing == extra == 0 else "NEEDS REVIEW",
    "summary": {
        "match": match,
        "partial": partial,
        "mismatch": mismatch,
        "missing": missing,
        "extra": extra,
    },
}
(staging / "check_data.json").write_text(json.dumps(data, indent=2) + "\n")
PYJSON
log_info "Check data saved to $STAGING_DIR/check_data.json"
