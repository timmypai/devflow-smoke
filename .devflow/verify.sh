#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${DEVFLOW_BASE_URL:?}" "${GITHUB_SHA:?}"
[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]]
export DEVFLOW_EXPECTED_REVISION="${DEVFLOW_EXPECTED_REVISION:-$GITHUB_SHA}"
export DEVFLOW_VERSION_ENDPOINT="${DEVFLOW_VERSION_ENDPOINT-1}"
export DEVFLOW_STATS_ENDPOINT="${DEVFLOW_STATS_ENDPOINT-1}"
export DEVFLOW_VERIFY_PHASE="${DEVFLOW_VERIFY_PHASE:-candidate}"
export DEVFLOW_NET="${DEVFLOW_NET:-host}"
export DEVFLOW_INNER_URL="${DEVFLOW_INNER_URL:-$DEVFLOW_BASE_URL}"
root="${DEVFLOW_EVIDENCE:-$PWD/.devflow/evidence}"
mkdir -p "$root"
export DEVFLOW_EVIDENCE
DEVFLOW_EVIDENCE=$(mktemp -d "$root/attempt-XXXXXXXX")
printf '%s\n' "$GITHUB_SHA" > "$DEVFLOW_EVIDENCE/source-sha.txt"
printf '%s\n' "$DEVFLOW_EXPECTED_REVISION" > "$DEVFLOW_EVIDENCE/expected-revision.txt"
printf '%s\n' "${RUNNER_NAME:-local} ${RUNNER_ARCH:-$(uname -m)}" > "$DEVFLOW_EVIDENCE/runner.txt"
printf '%s\n' "$DEVFLOW_VERIFY_PHASE" > "$DEVFLOW_EVIDENCE/phase.txt"
trap 'rc=$?; printf "%s\n" "$rc" > "$DEVFLOW_EVIDENCE/exit-code.txt"' EXIT
case "$DEVFLOW_VERIFY_PHASE" in candidate|rollback) ;; *) exit 1 ;; esac
case "$DEVFLOW_VERSION_ENDPOINT" in 1|''|'<no value>') ;; *) exit 1 ;; esac
case "$DEVFLOW_STATS_ENDPOINT" in
  1) [[ "$DEVFLOW_VERSION_ENDPOINT" == 1 ]]; contract=stats ;;
  ''|'<no value>') [[ "$DEVFLOW_VERIFY_PHASE" == rollback ]]; contract=legacy ;;
  *) echo 'Unsupported stats capability' >&2; exit 1 ;;
esac
# Candidates always require the current contract, never response-based fallback.
[[ "$DEVFLOW_VERIFY_PHASE" == rollback || "$contract" == stats ]]
printf '%s\n' "$contract" > "$DEVFLOW_EVIDENCE/contract.txt"
args=()
if [[ "$DEVFLOW_VERSION_ENDPOINT" == 1 ]]; then
  args=(--expected-revision "$DEVFLOW_EXPECTED_REVISION")
else
  echo 'Legacy rollback: /version NOT verified' | tee "$DEVFLOW_EVIDENCE/legacy.txt"
fi
journey() {
  local id="$1" description="$2"
  shift 2
  echo "Journey $id: $description" | tee -a "$DEVFLOW_EVIDENCE/journeys.log"
  "$@" 2>&1 | tee "$DEVFLOW_EVIDENCE/$id.log"
}
http_journey() {
  python3 smoke.py "$DEVFLOW_BASE_URL" "${args[@]}" 2>&1 | tee "$DEVFLOW_EVIDENCE/http.log"
}
browser_journey() {
  .devflow/playwright.sh 2>&1 | tee "$DEVFLOW_EVIDENCE/browser.log"
}
if [[ "$contract" == stats ]]; then
  journey AC-1 'GET /stats JSON contract and increasing shared HTTP snapshots' http_journey
  journey AC-2 'Visible homepage count, refresh and same-origin HTTP/DOM snapshots' browser_journey
else
  args+=(--legacy-home)
  echo 'Legacy rollback only: stats AC-1/AC-2 NOT verified' | tee -a "$DEVFLOW_EVIDENCE/legacy.txt"
  journey legacy-http 'Old plain-text homepage and supported version contract' http_journey
  journey legacy-browser 'Old plain-text homepage in Chromium' browser_journey
fi
python3 .devflow/check-evidence.py "$DEVFLOW_EVIDENCE"
if [[ "$contract" == stats ]]; then
  printf 'AC-1 PASS\nAC-2 PASS\n' | tee "$DEVFLOW_EVIDENCE/result.txt"
  if [[ "$DEVFLOW_VERIFY_PHASE" == candidate ]]; then
    cp "$DEVFLOW_EVIDENCE/AC-2.png" "$root/AC-2.png"
  fi
else
  echo 'Legacy rollback PASS; stats AC-1/AC-2 NOT verified' | tee "$DEVFLOW_EVIDENCE/result.txt"
fi
