#!/usr/bin/env bash
# Only this fixed, ignored directory is removed; no arbitrary input path.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf -- .devflow/evidence
mkdir -p .devflow/evidence
printf '%s\n' "${GITHUB_SHA:?}" > .devflow/evidence/source-sha.txt
printf 'Verification not yet completed; see attempt exit codes and workflow conclusion.\n' > .devflow/evidence/status.txt
