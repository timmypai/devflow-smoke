#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${GITHUB_SHA:?set GITHUB_SHA to the full source commit}"
[[ "$GITHUB_SHA" =~ ^[0-9a-f]{40}$ ]] || { echo "invalid source SHA" >&2; exit 1; }
[[ "$(git rev-parse HEAD)" == "$GITHUB_SHA" ]] || { echo "checkout SHA mismatch" >&2; exit 1; }
image="devflow-smoke-ci:${GITHUB_SHA}"
container=""
cleanup() {
  if [[ -n "$container" ]]; then
    docker logs "$container" || true
    docker rm -f "$container"
  fi
}
trap cleanup EXIT
docker build --build-arg "VCS_REF=$GITHUB_SHA" -t "$image" .
container=$(docker run -d -p 127.0.0.1::8080 -e "DEVFLOW_REVISION=$GITHUB_SHA" "$image")
binding=$(docker port "$container" 8080/tcp)
python3 smoke.py "http://${binding}" --expected-revision "$GITHUB_SHA"
image_id=$(docker inspect --format '{{.Image}}' "$container")
revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image_id")
printf 'source=%s container=%s image=%s revision=%s\n' "$GITHUB_SHA" "$container" "$image_id" "$revision"
[[ "$revision" == "$GITHUB_SHA" ]]
stats_endpoint=$(docker image inspect --format '{{index .Config.Labels "io.devflow.stats-endpoint"}}' "$image_id")
[[ "$stats_endpoint" == 1 ]]
