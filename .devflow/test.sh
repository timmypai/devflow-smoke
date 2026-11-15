#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash -n .devflow/*.sh
exec python3 -m unittest discover -s tests -v
