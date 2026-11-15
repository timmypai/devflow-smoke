#!/usr/bin/env bash
# devflow 部署：在 Oracle VM self-hosted runner（rootless Docker）上執行。
# build → up → 雙端點 smoke / provenance；失敗時回滾到上一個成功版本。
set -euo pipefail
cd "$(dirname "$0")/.."
set -a; . .devflow/config.env; set +a

if [[ "${DEVFLOW_DEPLOY:-true}" == "false" ]]; then
  echo "DEVFLOW_DEPLOY=false; skip deploy"; exit 0
fi

: "${DEVFLOW_APP:?}" "${DEVFLOW_PORT:?}"
SHA="${GITHUB_SHA:-$(git rev-parse HEAD)}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "invalid source SHA" >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$SHA" ]] || { echo "checkout SHA mismatch" >&2; exit 1; }
export GITHUB_SHA="$SHA"
REPO_IMAGE="devflow/${DEVFLOW_APP}"
export DEVFLOW_IMAGE="${REPO_IMAGE}:${SHA:0:12}"
COMPOSE=(docker compose -p "devflow-${DEVFLOW_APP}" -f deploy/compose.yml)
umask 077
touch deploy/.env   # 本服務不需要 secrets；保留 compose 契約。

healthy() {
  python3 smoke.py "http://127.0.0.1:${DEVFLOW_PORT}" | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
}

verify_deployment() {
  local container image_id revision running
  healthy || return 1
  container=$("${COMPOSE[@]}" ps -q app) || return 1
  [[ -n "$container" ]] || return 1
  running=$(docker inspect --format '{{.State.Running}}' "$container") || return 1
  image_id=$(docker inspect --format '{{.Image}}' "$container") || return 1
  revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image_id") || return 1
  {
    printf '### Deployment provenance\n'
    printf 'GITHUB_SHA=%s\n\nrunner=%s architecture=%s\n\n' "$GITHUB_SHA" "${RUNNER_NAME:-local}" "${RUNNER_ARCH:-$(uname -m)}"
    printf 'container=%s\n\nimage=%s\n\nOCI revision=%s\n' "$container" "$image_id" "$revision"
  } | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  [[ "$running" == true && "$revision" == "$GITHUB_SHA" ]]
}

echo "::group::build ${DEVFLOW_IMAGE}"
"${COMPOSE[@]}" build --pull
echo "::endgroup::"

if "${COMPOSE[@]}" up -d --remove-orphans && verify_deployment; then
  docker tag "${DEVFLOW_IMAGE}" "${REPO_IMAGE}:live"
  echo "devflow: ${DEVFLOW_APP} ${SHA:0:12} healthy on 127.0.0.1:${DEVFLOW_PORT}${DEVFLOW_HEALTH_PATH:-}"
  exit 0
fi

echo "::error::devflow: ${DEVFLOW_APP} ${SHA:0:12} failed deployment verification" >&2
"${COMPOSE[@]}" logs --tail 80 >&2 || true
if docker image inspect "${REPO_IMAGE}:live" >/dev/null 2>&1; then
  echo "devflow: rolling back to ${REPO_IMAGE}:live" >&2
  DEVFLOW_IMAGE="${REPO_IMAGE}:live" "${COMPOSE[@]}" up -d --no-build --remove-orphans
  if healthy; then echo "devflow: rollback healthy" >&2; else echo "::error::devflow: rollback also unhealthy" >&2; fi
fi
exit 1
