#!/usr/bin/env bash
# End-to-end Terminal Two pull, feature build, train, and a sample allocation.
# Source failures are logged and do not stop the run unless core macro data
# is missing. Run from anywhere; this script cds to the repo root.
set -euo pipefail
cd "$(dirname "$0")/.."
export PYTHONUNBUFFERED=1

python -m src.ingestion.run
python -m src.features.build
python -m src.model.train
python -m src.cli report
python -m src.cli recommend --budget 100000
python -m unittest discover -s tests -v
