#!/usr/bin/env bash
# End-to-end Terminal Two pull, feature build, train, and a sample allocation.
# Source failures are logged and do not stop the run unless core macro data
# is missing. Run from anywhere; this script cds to the repo root.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1

if command -v python >/dev/null 2>&1; then
  PY=python
elif command -v python3 >/dev/null 2>&1; then
  PY=python3
else
  echo "Python 3 is required." >&2
  exit 1
fi

"$PY" -m src.ingestion.run
"$PY" -m src.features.build
"$PY" -m src.model.train
"$PY" -m src.cli report
"$PY" -m src.cli recommend --budget 100000
"$PY" -m unittest discover -s tests -v
