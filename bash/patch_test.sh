#!/bin/bash
# Step 4: Run tests and collect results (bash version)
#
# Usage:
#     ./patch_test.sh                        # test today's applied patches
#     ./patch_test.sh --date 2026-03-25      # test specific date
#
# Environment variables (override defaults):
#     PATCH_PIPELINE_BUILD_COMMAND (e.g., "make -j$(nproc)")
#     PATCH_PIPELINE_UNIT_TEST_COMMAND (e.g., "pytest tests/")
#     PATCH_PIPELINE_TEST_TIMEOUT_SECONDS (default: 600)

set -euo pipefail

# ============================================================================
# Configuration
# ============================================================================

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_PATH="${REPO_PATH:-.}"
DATE="${DATE:-$(date +%Y-%m-%d)}"
STAGING_PATH="${STAGING_PATH:-.patch-staging}"
BUILD_CMD="${PATCH_PIPELINE_BUILD_COMMAND:-make -j$(nproc)}"
TEST_CMD="${PATCH_PIPELINE_UNIT_TEST_COMMAND:-pytest tests/}"
SILICON_RESULT="${PATCH_PIPELINE_SILICON_RESULT:-}"
SILICON_NOTES="${PATCH_PIPELINE_SILICON_NOTES:-}"
SILICON_ATTACHMENT="${PATCH_PIPELINE_SILICON_ATTACHMENT:-}"
TEST_TIMEOUT_SECONDS="${PATCH_PIPELINE_TEST_TIMEOUT_SECONDS:-600}"
PROMPT_ENABLED=true

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
    --build-cmd)
      BUILD_CMD="$2"
      shift 2
      ;;
    --test-cmd)
      TEST_CMD="$2"
      shift 2
      ;;
    --silicon-result)
      SILICON_RESULT="$2"
      shift 2
      ;;
    --silicon-notes)
      SILICON_NOTES="$2"
      shift 2
      ;;
    --silicon-attachment)
      SILICON_ATTACHMENT="$2"
      shift 2
      ;;
    --timeout)
      TEST_TIMEOUT_SECONDS="$2"
      shift 2
      ;;
    --no-prompt)
      PROMPT_ENABLED=false
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

run_command_with_timeout() {
  local command="$1"
  local timeout_seconds="$2"
  python3 - "$command" "$timeout_seconds" <<'PYTIMEOUT'
import subprocess
import sys

command, timeout_seconds = sys.argv[1], int(sys.argv[2])
try:
    subprocess.run(command, shell=True, executable="/bin/bash", check=True, timeout=timeout_seconds)
except subprocess.TimeoutExpired:
    raise SystemExit(124)
except subprocess.CalledProcessError as exc:
    raise SystemExit(exc.returncode)
PYTIMEOUT
}

# ============================================================================
# Validation
# ============================================================================
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

log_info "Testing patches from $DATE"

# ============================================================================
# Run Build Test
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"
echo "🔨 Running build: $BUILD_CMD"
echo "────────────────────────────────────────────────────────────"

BUILD_LOG=$(mktemp)
BUILD_PASS=true
BUILD_RESULT="PASS"
if cd "$REPO_PATH" && run_command_with_timeout "$BUILD_CMD" "$TEST_TIMEOUT_SECONDS" > "$BUILD_LOG" 2>&1; then
  log_success "Build passed"
else
  status=$?
  BUILD_PASS=false
  if [[ "$status" -eq 124 ]]; then
    BUILD_RESULT="TIMEOUT"
    log_warn "Build timed out after ${TEST_TIMEOUT_SECONDS}s (see $BUILD_LOG)"
  else
    BUILD_RESULT="FAIL"
    log_warn "Build failed (see $BUILD_LOG)"
  fi
fi

# ============================================================================
# Run Unit Tests
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"
echo "🧪 Running unit tests: $TEST_CMD"
echo "────────────────────────────────────────────────────────────"

TEST_LOG=$(mktemp)
TEST_PASS=true
TEST_RESULT="PASS"
if cd "$REPO_PATH" && run_command_with_timeout "$TEST_CMD" "$TEST_TIMEOUT_SECONDS" > "$TEST_LOG" 2>&1; then
  log_success "Unit tests passed"
else
  status=$?
  TEST_PASS=false
  if [[ "$status" -eq 124 ]]; then
    TEST_RESULT="TIMEOUT"
    log_warn "Unit tests timed out after ${TEST_TIMEOUT_SECONDS}s (see $TEST_LOG)"
  else
    TEST_RESULT="FAIL"
    log_warn "Unit tests failed (see $TEST_LOG)"
  fi
fi

# ============================================================================
# Prompt for Silicon Test Results
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"
echo "🤖 Silicon/Hardware Test Results"
echo "────────────────────────────────────────────────────────────"
echo ""
echo "Has hardware testing been completed? (PASS/FAIL/PENDING)"
echo "  PASS    - All hardware tests passed"
echo "  FAIL    - Hardware tests failed"
echo "  PENDING - Testing in progress or not applicable"
echo ""

if [[ -z "$SILICON_RESULT" && "$PROMPT_ENABLED" == "true" && -t 0 ]]; then
  read -r -p "Enter silicon test result [PENDING]: " input
  if [[ -n "$input" ]]; then
    SILICON_RESULT=$(echo "$input" | tr '[:lower:]' '[:upper:]')
  fi
fi
SILICON_RESULT="${SILICON_RESULT:-PENDING}"
if [[ "$SILICON_RESULT" == "SKIP" ]]; then
  SILICON_RESULT="SKIPPED"
fi
case "$SILICON_RESULT" in
  PASS|FAIL|PENDING|SKIPPED) ;;
  *)
    log_warn "Invalid result '$SILICON_RESULT' (expected PASS/FAIL/PENDING/SKIPPED), using PENDING"
    SILICON_RESULT="PENDING"
    ;;
esac

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"
echo "📊 Test Summary"
echo "────────────────────────────────────────────────────────────"
echo ""
echo "Build test      : $BUILD_RESULT"
echo "Unit tests      : $TEST_RESULT"
echo "Silicon tests   : $SILICON_RESULT"
echo ""

if [[ "$BUILD_PASS" == "true" && "$TEST_PASS" == "true" ]]; then
  log_success "All automated tests passed"
else
  log_warn "Some tests failed — review logs before integration"
fi

if [[ "$SILICON_RESULT" == "PENDING" ]]; then
  log_warn "Silicon tests pending — integration can proceed after approval"
fi

# ============================================================================
# Save test data for report
# ============================================================================

python3 - "$STAGING_DIR" "$BUILD_CMD" "$TEST_CMD" "$BUILD_RESULT" "$TEST_RESULT" "$SILICON_RESULT" "$SILICON_NOTES" "$SILICON_ATTACHMENT" "$BUILD_LOG" "$TEST_LOG" <<'PYJSON'
import json
import sys
from pathlib import Path

staging = Path(sys.argv[1])
build_cmd, test_cmd = sys.argv[2], sys.argv[3]
build_result, test_result = sys.argv[4], sys.argv[5]
silicon_result, silicon_notes, silicon_attachment = sys.argv[6:9]
build_log, test_log = sys.argv[9:11]
results = [
    {
        "test": "Build Check",
        "result": build_result,
        "notes": f"Command: {build_cmd}; log: {build_log}",
    },
    {
        "test": "Unit Test",
        "result": test_result,
        "notes": f"Command: {test_cmd}; log: {test_log}",
    },
    {
        "test": "Silicon Test",
        "result": silicon_result,
        "notes": silicon_notes,
    },
]
if silicon_attachment:
    results[-1]["attachment"] = silicon_attachment
(staging / "test_data.json").write_text(json.dumps(results, indent=2) + "\n")
PYJSON
log_info "Test data saved to $STAGING_DIR/test_data.json"
