#!/usr/bin/env bash
# Run AFTER starting HydraDB on an EMPTY data dir. Rebuilds the whole graph from saved files.
set -e
cd "$(dirname "$0")/.."
source .venv/bin/activate
python scripts/hydra_ping.py > /dev/null || true
python scripts/ingest_tools.py
python scripts/learn_graph.py
