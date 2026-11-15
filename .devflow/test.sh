#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash -n .devflow/test.sh .devflow/deploy.sh .devflow/container-smoke.sh
exec python3 -m unittest discover -s tests -v
