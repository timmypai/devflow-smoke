#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
for script in .devflow/*.sh; do bash -n "$script"; done
exec python3 -m unittest discover -s tests -v
