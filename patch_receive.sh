#!/bin/bash
# Step 1: Receive, validate, and review patches (bash version)
#
# Usage:
#     ./patch_receive.sh /mnt/sharepoint/BHS-B0/2026-03-26/
#     ./patch_receive.sh ./local-patches/
#     ./patch_receive.sh ./local-patches/ --date 2026-03-25
#     ./patch_receive.sh ./local-patches/ --force
#
# Environment variables (override defaults):
#     PATCH_PIPELINE_RELEASE
#     PATCH_PIPELINE_WORKING_BRANCH
#     PATCH_STAGING_PATH (default: .patch-staging)

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_PATH="${REPO_PATH:-.}"
DATE="${DATE:-$(date +%Y-%m-%d)}"
FORCE_FLAG=false
STAGING_PATH="${STAGING_PATH:-.patch-staging}"

# Binary file extensions to flag
BINARY_EXTS=("bin" "exe" "dll" "o" "obj" "rom" "fd" "cap")

# Parse command-line arguments
SOURCE_DIR=""
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
    -*)
      echo "Unknown option: $1" >&2
      exit 1
      ;;
    *)
      SOURCE_DIR="$1"
      shift
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

# Check if file has binary extension
is_binary_file() {
  local file="$1"
  local ext="${file##*.}"
  for binary_ext in "${BINARY_EXTS[@]}"; do
    if [[ "$ext" == "$binary_ext" ]]; then
      return 0
    fi
  done
  return 1
}

# Validate that file looks like git format-patch output
validate_patch() {
  local patch_file="$1"
  local reason=""
  
  if [[ ! -f "$patch_file" ]]; then
    echo "Cannot read file"
    return 1
  fi
  
  # Check for From header
  if ! head -20 "$patch_file" | grep -q "^From "; then
    echo "Missing 'From' header — not a git format-patch file"
    return 1
  fi
  
  # Check for Subject header
  if ! head -30 "$patch_file" | grep -q "^Subject:"; then
    echo "Missing 'Subject:' header"
    return 1
  fi
  
  # Check for diff content
  if ! grep -q "diff --git" "$patch_file"; then
    echo "Missing 'diff --git' — no actual diff content"
    return 1
  fi
  
  return 0
}

# Extract patch metadata
get_patch_info() {
  local patch_file="$1"
  
  local subject=""
  local author=""
  local files_count=0
  local insertions=0
  local deletions=0
  local file_list=""
  
  subject=$(grep -m1 "^Subject:" "$patch_file" | sed 's/^Subject: \[PATCH[^]]*\] *//')
  author=$(grep -m1 "^From:" "$patch_file" | sed 's/^From: *//')
  
  # Extract changed files from diff --git lines
  file_list=$(grep "^diff --git" "$patch_file" | sed 's|^diff --git a/||; s| b/.*||' | sort -u)
  files_count=$(echo "$file_list" | grep -c . || echo 0)
  
  # Try to extract insertions/deletions from stat line
  local stat_line
  stat_line=$(grep " files? changed" "$patch_file" | tail -1)
  if [[ -n "$stat_line" ]]; then
    insertions=$(echo "$stat_line" | grep -oP '\+\+\+|\K\d+(?= insertions)' | head -1 || echo 0)
    deletions=$(echo "$stat_line" | grep -oP '\-\-\-|\K\d+(?= deletions)' | head -1 || echo 0)
  fi
  
  # Output as key=value pairs
  echo "subject=$subject"
  echo "author=$author"
  echo "files_count=$files_count"
  echo "insertions=$insertions"
  echo "deletions=$deletions"
  echo "files=$file_list"
}

# ============================================================================
# Validation
# ============================================================================

if [[ -z "$SOURCE_DIR" ]]; then
  die "Usage: $0 <source-dir> [--date DATE] [--force]"
fi

SOURCE_DIR=$(cd "$SOURCE_DIR" && pwd)
if [[ ! -d "$SOURCE_DIR" ]]; then
  die "Source directory does not exist: $SOURCE_DIR"
fi

# Find all patch files
mapfile -t PATCH_FILES < <(find "$SOURCE_DIR" -maxdepth 1 -name "*.patch" -type f | sort)
if [[ ${#PATCH_FILES[@]} -eq 0 ]]; then
  die "No .patch files found in $SOURCE_DIR"
fi

log_info "Found ${#PATCH_FILES[@]} patch file(s) in $SOURCE_DIR"
echo ""

# ============================================================================
# Create staging directory
# ============================================================================

STAGING_DIR="$REPO_PATH/$STAGING_PATH/$DATE"

if [[ -d "$STAGING_DIR" ]] && [[ ${#PATCH_FILES[@]} -gt 0 ]] && [[ "$FORCE_FLAG" != "true" ]]; then
  # Check if staging dir already has patches
  if find "$STAGING_DIR" -maxdepth 1 -name "*.patch" -type f -quit 2>/dev/null | grep -q .; then
    die "Staging dir already has patches for $DATE. Use --force to overwrite."
  fi
fi

mkdir -p "$STAGING_DIR"

# ============================================================================
# Process patches
# ============================================================================

VALID_PATCHES=()
PATCH_INFOS=()
ERRORS=()
WARNINGS_TOTAL=()

for patch_file in "${PATCH_FILES[@]}"; do
  patch_name=$(basename "$patch_file")
  
  # Validate patch
  if ! validation_error=$(validate_patch "$patch_file"); then
    ERRORS+=("$patch_name: $validation_error")
    continue
  fi
  
  # Get patch info
  declare -A info
  while IFS='=' read -r key value; do
    info[$key]="$value"
  done < <(get_patch_info "$patch_file")
  
  # Check file size (arbitrary limit: 10 MB)
  size_kb=$(($(stat -f%z "$patch_file" 2>/dev/null || stat -c%s "$patch_file") / 1024))
  if [[ $size_kb -gt 10240 ]]; then
    ERRORS+=("$patch_name: Too large ($size_kb KB)")
    continue
  fi
  
  # Display patch info
  echo "────────────────────────────────────────────────────────────"
  echo "Patch: ${info[subject]}"
  echo "  Author : ${info[author]}"
  echo "  Changes: ${info[files_count]} file(s)  +${info[insertions]}/-${info[deletions]}"
  
  # List first 10 files
  if [[ -n "${info[files]}" ]]; then
    echo "${info[files]}" | head -10 | sed 's/^/    • /'
    local file_count=$(echo "${info[files]}" | grep -c . || echo 0)
    if [[ $file_count -gt 10 ]]; then
      echo "    ... and $((file_count - 10)) more"
    fi
  fi
  
  # Check for binary files
  local patch_warnings=()
  while IFS= read -r file; do
    if is_binary_file "$file"; then
      patch_warnings+=("Binary file: $file")
    fi
  done < <(echo "${info[files]}")
  
  if [[ ${#patch_warnings[@]} -gt 0 ]]; then
    for w in "${patch_warnings[@]}"; do
      echo "  ⚠️  $w"
      WARNINGS_TOTAL+=("$w")
    done
  fi
  
  # Copy patch to staging
  cp "$patch_file" "$STAGING_DIR/$patch_name"
  VALID_PATCHES+=("$patch_file")
  PATCH_INFOS+=("${info[subject]}")
done

# ============================================================================
# Summary report
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"

if [[ ${#VALID_PATCHES[@]} -gt 0 ]]; then
  log_success "${#VALID_PATCHES[@]} patch(es) staged to $STAGING_DIR"
  
  # Simple table: #, Subject, Files
  echo ""
  echo "| # | Subject | Files | +/- |"
  echo "|---|---------|-------|-----|"
  for i in "${!PATCH_INFOS[@]}"; do
    idx=$((i + 1))
    subject="${PATCH_INFOS[$i]}"
    # Get file count from original patch
    patch_file="${VALID_PATCHES[$i]}"
    files_count=$(grep -c "^diff --git" "$patch_file" || echo 0)
    insertions=$(grep " files? changed" "$patch_file" | tail -1 | grep -oP '\d+(?= insertions)' | head -1 || echo 0)
    deletions=$(grep " files? changed" "$patch_file" | tail -1 | grep -oP '\d+(?= deletions)' | head -1 || echo 0)
    printf "| %d | %.50s | %d | +%d/-%d |\n" "$idx" "$subject" "$files_count" "$insertions" "$deletions"
  done
fi

if [[ ${#ERRORS[@]} -gt 0 ]]; then
  log_warn "${#ERRORS[@]} patch(es) skipped:"
  for err in "${ERRORS[@]}"; do
    echo "  • $err"
  done
fi

if [[ ${#WARNINGS_TOTAL[@]} -gt 0 ]]; then
  log_warn "Total warnings: ${#WARNINGS_TOTAL[@]}"
fi
