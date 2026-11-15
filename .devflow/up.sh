#!/usr/bin/env bash
# Ephemeral PR service. Never touches the deployment project, :live or fixed port.
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . .devflow/config.env; set +a
: "${GITHUB_SHA:?}" "${GITHUB_ENV:?}"
[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]]
export DEVFLOW_PORT=0
export DEVFLOW_IMAGE="devflow/${DEVFLOW_APP}:verify-${GITHUB_SHA}"
project="devflow-verify-${GITHUB_RUN_ID:?}-${GITHUB_RUN_ATTEMPT:?}-${RUNNER_ARCH,,}"
COMPOSE=(docker compose -p "$project" -f deploy/compose.yml)
touch deploy/.env
# Record before build so workflow always-cleanup works after partial startup.
printf 'DEVFLOW_VERIFY_PROJECT=%s\nDEVFLOW_IMAGE=%s\nDEVFLOW_PORT=0\n' "$project" "$DEVFLOW_IMAGE" >> "$GITHUB_ENV"
"${COMPOSE[@]}" build --pull
"${COMPOSE[@]}" up -d --remove-orphans
address=$("${COMPOSE[@]}" port app "$DEVFLOW_APP_PORT")
[[ "$address" == 127.0.0.1:* ]]
printf 'DEVFLOW_BASE_URL=http://%s\nDEVFLOW_INNER_URL=http://app:%s\nDEVFLOW_NET=%s_default\n' "$address" "$DEVFLOW_APP_PORT" "$project" >> "$GITHUB_ENV"
