#!/usr/bin/env bash
# Quality-only dependency is pinned/installed by the hosted quality workflow.
# Explicit test root: tool defaults `discover -s .` find zero tests in this repo.
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -c 'import unittest; assert unittest.defaultTestLoader.discover("tests").countTestCases() > 0, "no tests discovered"'
mkdir -p target/coverage/python
python3 -m coverage run --data-file=target/coverage/python/.coverage --source=app,smoke,.devflow \
  -m unittest discover -s tests -v
python3 -m coverage lcov --data-file=target/coverage/python/.coverage -o target/coverage/python/lcov.info
