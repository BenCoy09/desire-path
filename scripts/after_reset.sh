#!/usr/bin/env bash
cd ~/desire-path && source .venv/bin/activate
python scripts/wait_quota.py
python -u scripts/scale_test.py --sizes 300,1000 --methods graph
python -u scripts/run_graph.py --split test --rerun
python -u scripts/run_graph.py --split test --rerun
python -u scripts/scale_test.py --sizes 100 --methods preload
echo ALL DONE
