#!/usr/bin/env bash
# Read-only, best-effort diagnostics. Raw files never enter the artifact directory.
# Usage: capture.sh <exact compose project> <label> [docker logs --since]
set -uo pipefail
cd "$(dirname "$0")/.." || exit 0
project=${1:-} label=${2:-} since=${3:-30m}
if [[ ! $project =~ ^[a-z0-9][a-z0-9_.-]*$ || ! $label =~ ^[A-Za-z0-9][A-Za-z0-9_-]*$ || ! $since =~ ^[0-9A-Za-z:.+-]+$ ]]; then
  echo 'capture: invalid arguments' >&2; exit 0
fi
set -a; . .devflow/config.env; set +a
# No caller-controlled output path or traversal; reject symlinks before cleanup.
root="$PWD/.devflow/diagnostics"
[[ ! -L "$root" && ! -L "$root/$label" ]] || exit 0
umask 077
mkdir -p "$root" || exit 0
stage=$(mktemp -d "$PWD/.devflow/.capture-XXXXXXXX") || exit 0
trap 'rm -rf -- "$stage"' EXIT
trap 'exit 0' TERM INT
mkdir "$stage/logs"
err="$stage/errors.txt"
filter=(--filter "label=com.docker.compose.project=$project")
timeout 15 docker ps -a "${filter[@]}" --format '{{json .}}' >"$stage/ps.jsonl" 2>>"$err"
mapfile -t ids < <(timeout 15 docker ps -aq "${filter[@]}" 2>>"$err")
# State includes healthcheck output: redact every output file, not only logs.
fmt='{"name":{{json .Name}},"service":{{json (index .Config.Labels "com.docker.compose.service")}},"image":{{json .Config.Image}},"image_id":{{json .Image}},"restart_count":{{.RestartCount}},"state":{{json .State}}}'
for id in "${ids[@]}"; do
  [[ $id =~ ^[a-f0-9]{12,64}$ ]] || continue
  timeout 15 docker inspect --format "$fmt" "$id" >>"$stage/state.jsonl" 2>>"$err"
  timeout 15 docker logs --timestamps --since "$since" --tail 2000 "$id" >"$stage/logs/$id.log" 2>&1
done
base=${DEVFLOW_BASE_URL:-http://127.0.0.1:${DEVFLOW_PORT}}
# Only local HTTP probes, never send credentials or follow redirects.
if [[ $base =~ ^http://127\.0\.0\.1:[0-9]+$ && -n ${DEVFLOW_HEALTH_PATH:-} ]]; then
  curl -sS --max-time 5 --max-filesize 4096 -o "$stage/health-body.txt" \
    -w '{"http_code":"%{http_code}","time_total":%{time_total}}\n' \
    "$base${DEVFLOW_HEALTH_PATH}" >"$stage/health.json" 2>>"$err"
fi
{ printf '# disk (repo filesystem)\n'; df -hP .; printf '# memory\n'; grep -E '^(MemTotal|MemAvailable|SwapFree):' /proc/meminfo; } >"$stage/host.txt" 2>>"$err"
sha=${GITHUB_SHA:-$(git rev-parse HEAD 2>/dev/null || true)}
[[ $sha =~ ^[0-9a-f]{40}$ ]] || sha=
printf '{"label":"%s","project":"%s","since":"%s","captured_at":"%s","git_sha":"%s","containers":%d}\n' \
  "$label" "$project" "$since" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$sha" "${#ids[@]}" >"$stage/manifest.json"
if ! python3 .devflow/redact.py deploy/.env "$stage" >/dev/null 2>&1; then
  # Drop ALL raw output, including State, ps, health and errors. No partial publish.
  rm -rf -- "$stage"
  mkdir -p "$stage"
  printf 'redaction failed: all diagnostic payloads removed (fail closed)\n' >"$stage/errors.txt"
fi
[[ -s "$stage/errors.txt" ]] || rm -f -- "$stage/errors.txt"
rm -rf -- "$root/$label"
mv -- "$stage" "$root/$label" || exit 0
printf 'capture: %s (%s containers)\n' "$label" "${#ids[@]}"
exit 0
