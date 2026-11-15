#!/usr/bin/env bash
# Baseline infrastructure journeys, NOT the future stats AC-1 / AC-2.
set -euo pipefail
cd "$(dirname "$0")/.."
: "${DEVFLOW_BASE_URL:?}" "${GITHUB_SHA:?}"
[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]
export DEVFLOW_EXPECTED_REVISION="${DEVFLOW_EXPECTED_REVISION:-$GITHUB_SHA}"
export DEVFLOW_VERSION_ENDPOINT="${DEVFLOW_VERSION_ENDPOINT-1}"
export DEVFLOW_NET="${DEVFLOW_NET:-host}"
export DEVFLOW_INNER_URL="${DEVFLOW_INNER_URL:-$DEVFLOW_BASE_URL}"
# A new directory per attempt; never accept evidence from an earlier invocation.
root="${DEVFLOW_EVIDENCE:-$PWD/.devflow/evidence}"
mkdir -p "$root"
export DEVFLOW_EVIDENCE
DEVFLOW_EVIDENCE=$(mktemp -d "$root/attempt-XXXXXXXX")
printf '%s\n' "$GITHUB_SHA" > "$DEVFLOW_EVIDENCE/source-sha.txt"
printf '%s\n' "$DEVFLOW_EXPECTED_REVISION" > "$DEVFLOW_EVIDENCE/expected-revision.txt"
printf '%s\n' "${RUNNER_NAME:-local} ${RUNNER_ARCH:-$(uname -m)}" > "$DEVFLOW_EVIDENCE/runner.txt"
trap 'rc=$?; printf "%s\n" "$rc" > "$DEVFLOW_EVIDENCE/exit-code.txt"' EXIT
args=()
if [[ "$DEVFLOW_VERSION_ENDPOINT" == 1 ]]; then
  args=(--expected-revision "$DEVFLOW_EXPECTED_REVISION")
else
  echo 'Legacy rollback: /version NOT verified' | tee "$DEVFLOW_EVIDENCE/legacy.txt"
fi
python3 smoke.py "$DEVFLOW_BASE_URL" "${args[@]}" 2>&1 | tee "$DEVFLOW_EVIDENCE/http.log"
.devflow/playwright.sh 2>&1 | tee "$DEVFLOW_EVIDENCE/browser.log"
python3 .devflow/check-evidence.py "$DEVFLOW_EVIDENCE"
echo 'Baseline HTTP + browser journeys PASS (not stats AC-1/AC-2)' | tee "$DEVFLOW_EVIDENCE/result.txt"
