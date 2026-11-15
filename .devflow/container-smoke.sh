#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
: "${GITHUB_SHA:?set GITHUB_SHA to the full source commit}"
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
container=$(docker run -d -p 127.0.0.1::8080 "$image")
binding=$(docker port "$container" 8080/tcp)
python3 smoke.py "http://${binding}"
image_id=$(docker inspect --format '{{.Image}}' "$container")
revision=$(docker image inspect --format '{{index .Config.Labels "org.opencontainers.image.revision"}}' "$image_id")
printf 'source=%s container=%s image=%s revision=%s\n' "$GITHUB_SHA" "$container" "$image_id" "$revision"
[[ "$revision" == "$GITHUB_SHA" ]]
