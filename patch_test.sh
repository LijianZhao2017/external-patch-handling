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

BUILD_PASS=true
if cd "$REPO_PATH" && eval "$BUILD_CMD" > /tmp/build.log 2>&1; then
  log_success "Build passed"
else
  log_warn "Build failed (see /tmp/build.log)"
  BUILD_PASS=false
fi

# ============================================================================
# Run Unit Tests
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"
echo "🧪 Running unit tests: $TEST_CMD"
echo "────────────────────────────────────────────────────────────"

TEST_PASS=true
if cd "$REPO_PATH" && eval "$TEST_CMD" > /tmp/test.log 2>&1; then
  log_success "Unit tests passed"
else
  log_warn "Unit tests failed (see /tmp/test.log)"
  TEST_PASS=false
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

SILICON_RESULT="PENDING"
read -p "Enter silicon test result [PENDING]: " -r input
if [[ -n "$input" ]]; then
  SILICON_RESULT=$(echo "$input" | tr '[:lower:]' '[:upper:]')
fi

# ============================================================================
# Summary
# ============================================================================

echo ""
echo "────────────────────────────────────────────────────────────"
echo "📊 Test Summary"
echo "────────────────────────────────────────────────────────────"
echo ""
echo "Build test      : $([ "$BUILD_PASS" = "true" ] && echo "✅ PASS" || echo "❌ FAIL")"
echo "Unit tests      : $([ "$TEST_PASS" = "true" ] && echo "✅ PASS" || echo "❌ FAIL")"
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

TEST_DATA=$(cat <<EOF
{
  "date": "$DATE",
  "build_cmd": "$BUILD_CMD",
  "build_pass": $([[ "$BUILD_PASS" == "true" ]] && echo "true" || echo "false"),
  "test_cmd": "$TEST_CMD",
  "test_pass": $([[ "$TEST_PASS" == "true" ]] && echo "true" || echo "false"),
  "silicon_result": "$SILICON_RESULT",
  "build_log": "/tmp/build.log",
  "test_log": "/tmp/test.log"
}
EOF
)

echo "$TEST_DATA" | tee "$STAGING_DIR/test_data.json" > /dev/null
log_info "Test data saved to $STAGING_DIR/test_data.json"
