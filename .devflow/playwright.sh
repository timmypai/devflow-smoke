#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${DEVFLOW_EVIDENCE:?}" "${DEVFLOW_INNER_URL:?}" "${DEVFLOW_NET:?}"
# Official image includes native Chromium for both amd64 and arm64.
# Timeout kills the client, --rm and explicit trap also remove its container.
name="devflow-browser-${GITHUB_RUN_ID:-local}-${GITHUB_RUN_ATTEMPT:-1}-$$"
trap 'docker rm -f "$name" >/dev/null 2>&1 || true' EXIT
relative=$(python3 -c 'import os; print(os.path.relpath(os.environ["DEVFLOW_EVIDENCE"], os.getcwd()))')
[[ "$relative" != ../* && "$relative" != .. ]]
# Rootless UID 0 maps to the runner owner; rootful Docker needs its real UID.
user="$(id -u):$(id -g)"
security=$(docker info --format '{{json .SecurityOptions}}')
if [[ "$security" == *rootless* ]]; then user=0:0; fi
timeout 300 docker run --rm --name "$name" --init --ipc=host \
  --network "$DEVFLOW_NET" --user "$user" \
  -e HOME=/tmp -e CI=1 -e DEVFLOW_INNER_URL -e DEVFLOW_EXPECTED_REVISION \
  -e DEVFLOW_VERSION_ENDPOINT -e DEVFLOW_STATS_ENDPOINT -e DEVFLOW_VERIFY_PHASE \
  -e DEVFLOW_EVIDENCE="/work/$relative" \
  -v "$PWD:/work" -w /work/.devflow/ui \
  mcr.microsoft.com/playwright:v1.58.2-noble \
  bash -ec 'npm ci --no-audit --no-fund && npx --no-install playwright test'
