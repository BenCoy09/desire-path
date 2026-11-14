#!/usr/bin/env bash
cd ~/desire-path && source .venv/bin/activate
pkill -f scripts/traverse.py; sleep 2
for ttl in 0 60; do
  CACHE_TTL=$ttl python scripts/traverse.py >/dev/null 2>&1 &
  PID=$!
  for i in $(seq 1 30); do curl -sf localhost:8099/health >/dev/null && break; sleep 1; done
  echo "=== CACHE_TTL=$ttl (fresh start) ==="
  python scripts/load_test.py | tee results/load_ttl$ttl.txt
  kill $PID; sleep 2
done
