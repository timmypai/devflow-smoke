#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for script in .devflow/*.sh; do bash -n "$script"; done
# The base checkout must contain this helper: P2 overlays only test.sh + the test file.
exec python3 .devflow/unittest-runner.py
