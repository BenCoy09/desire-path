#!/usr/bin/env bash
cd ~/desire-path && source .venv/bin/activate
python scripts/wait_quota.py
python -u scripts/run_graph.py --split test --rerun
python -u scripts/run_graph.py --split test --rerun
[ -f scripts/run_hybrid.py ] && python -u scripts/run_hybrid.py
python -u scripts/scale_test.py --sizes 300,1000 --methods graph
[ -f scripts/run_prereq.py ] && python -u scripts/run_prereq.py
echo ALL DONE
