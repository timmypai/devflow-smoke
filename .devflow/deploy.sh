#!/usr/bin/env bash
# devflow 部署：在 Oracle VM self-hosted runner（rootless Docker）上執行。
# build → up → stats/HTML journeys / provenance；失敗時回滾到上一個成功版本。
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
  python3 smoke.py "http://127.0.0.1:${DEVFLOW_PORT}" "$@" | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
}

verify_deployment() {
  local expected_revision="$1" version_endpoint="${2-1}" stats_endpoint="${3-1}"
  local args=()
  if [[ "$stats_endpoint" != 1 ]]; then
    args+=(--legacy-home)
    echo "devflow: legacy homepage rollback; stats AC-1/AC-2 NOT verified" | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  fi
  local container image_id revision running actual_stats actual_version
  if [[ "$version_endpoint" == 1 ]]; then
    healthy "${args[@]}" --expected-revision "$expected_revision" || return 1
  else
    echo "devflow: legacy rollback; checking /health and / only, /version NOT verified" | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
    healthy "${args[@]}" || return 1
  fi
  container=$("${COMPOSE[@]}" ps -q app) || return 1
  [[ -n "$container" ]] || return 1
  running=$(docker inspect --format '{{.State.Running}}' "$container") || return 1
  image_id=$(docker inspect --format '{{.Image}}' "$container") || return 1
  revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image_id") || return 1
  {
    printf '### Deployment provenance\n'
    printf 'GITHUB_SHA=%s\n\nrunner=%s architecture=%s\n\n' "$GITHUB_SHA" "${RUNNER_NAME:-local}" "${RUNNER_ARCH:-$(uname -m)}"
    printf 'expected revision=%s\n\n' "$expected_revision"
    printf 'container=%s\n\nimage=%s\n\nOCI revision=%s\n' "$container" "$image_id" "$revision"
  } | tee -a "${GITHUB_STEP_SUMMARY:-/dev/null}"
  actual_stats=$(docker image inspect --format '{{index .Config.Labels "io.devflow.stats-endpoint"}}' "$image_id") || return 1
  actual_version=$(docker image inspect --format '{{index .Config.Labels "io.devflow.version-endpoint"}}' "$image_id") || return 1
  [[ "$running" == true && "$revision" == "$expected_revision" && "$actual_stats" == "$stats_endpoint" && "$actual_version" == "$version_endpoint" ]]
}

echo "::group::build ${DEVFLOW_IMAGE}"
"${COMPOSE[@]}" build --pull
echo "::endgroup::"

# Workflow clears the evidence root once; attempts isolate candidate and rollback.
export DEVFLOW_EVIDENCE="${DEVFLOW_EVIDENCE:-$PWD/.devflow/evidence}"
run_journeys() {
  DEVFLOW_BASE_URL="http://127.0.0.1:${DEVFLOW_PORT}" \
  DEVFLOW_NET="devflow-${DEVFLOW_APP}_default" \
  DEVFLOW_INNER_URL="http://app:${DEVFLOW_APP_PORT}" \
  DEVFLOW_EXPECTED_REVISION="$1" DEVFLOW_VERSION_ENDPOINT="${2-1}" \
  DEVFLOW_STATS_ENDPOINT="${3-1}" DEVFLOW_VERIFY_PHASE="${4-candidate}" \
    .devflow/verify.sh
}

if "${COMPOSE[@]}" up -d --remove-orphans && verify_deployment "$SHA" && run_journeys "$SHA"; then
  docker tag "${DEVFLOW_IMAGE}" "${REPO_IMAGE}:live"
  echo "devflow: ${DEVFLOW_APP} ${SHA:0:12} healthy on 127.0.0.1:${DEVFLOW_PORT}${DEVFLOW_HEALTH_PATH:-}"
  exit 0
fi

echo "::error::devflow: ${DEVFLOW_APP} ${SHA:0:12} failed deployment verification" >&2
"${COMPOSE[@]}" logs --tail 80 >&2 || true
if docker image inspect "${REPO_IMAGE}:live" >/dev/null 2>&1; then
  rollback_revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "${REPO_IMAGE}:live")
  [[ "$rollback_revision" =~ ^[0-9a-f]{40}$ ]] || { echo "::error::invalid rollback OCI revision" >&2; exit 1; }
  version_endpoint=$(docker image inspect --format '{{index .Config.Labels "io.devflow.version-endpoint"}}' "${REPO_IMAGE}:live")
  case "$version_endpoint" in
    1|''|'<no value>') ;;
    *) echo "::error::unsupported rollback version contract" >&2; exit 1 ;;
  esac
  stats_endpoint=$(docker image inspect --format '{{index .Config.Labels "io.devflow.stats-endpoint"}}' "${REPO_IMAGE}:live")
  case "$stats_endpoint" in
    1) [[ "$version_endpoint" == 1 ]] || { echo "::error::inconsistent rollback capabilities" >&2; exit 1; } ;;
    ''|'<no value>') ;;
    *) echo "::error::unsupported rollback stats contract" >&2; exit 1 ;;
  esac
  echo "devflow: rolling back to ${REPO_IMAGE}:live" >&2
  if GITHUB_SHA="$rollback_revision" DEVFLOW_IMAGE="${REPO_IMAGE}:live" "${COMPOSE[@]}" up -d --no-build --remove-orphans \
      && verify_deployment "$rollback_revision" "$version_endpoint" "$stats_endpoint" \
      && run_journeys "$rollback_revision" "$version_endpoint" "$stats_endpoint" rollback; then
    echo "devflow: rollback healthy" >&2
  else
    echo "::error::devflow: rollback also unhealthy" >&2
  fi
fi
exit 1
