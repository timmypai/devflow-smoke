#!/usr/bin/env bash
# Only the exact temporary project allocated to this run/attempt/architecture.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . .devflow/config.env; set +a
expected="devflow-verify-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}-${RUNNER_ARCH,,}"
[[ "${DEVFLOW_VERIFY_PROJECT:?}" == "$expected" ]] || { echo 'refusing foreign project' >&2; exit 1; }
export DEVFLOW_PORT=0
: "${DEVFLOW_IMAGE:?}" "${GITHUB_SHA:?}"
docker compose -p "$expected" -f deploy/compose.yml down --volumes --remove-orphans
