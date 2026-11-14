#!/usr/bin/env bash
set -euo pipefail

ROOT=/data
mkdir -p $ROOT/store $ROOT/node-cache
head -c 32 /dev/urandom | od -An -tx1 | tr -d ' \n' > $ROOT/token

export CLOUD_PROVIDER=local LOCAL_PATH=$ROOT/store GRAPH_DATA_PATH=data
export GRAPH_NAMESPACE=default GRAPH_ID=default
export GRAPH_CELL_ID=cell-0 GRAPH_CELLS=cell-0 GRAPH_NODE_ID=node-mcp
export GRAPH_AUTH_TOKEN_FILE=$ROOT/token
export GRAPH_ALLOW_PLAINTEXT=true
export GRAPH_DATA_CACHE_BYTES=33554432
export GRAPH_DATA_CACHE_DIR=$ROOT/node-cache
export GRAPH_BOLT_ADDR=127.0.0.1:28687
export GRAPH_ADVERTISED_BOLT_ADDR=127.0.0.1:28687
export GRAPH_BOLT_NODE_ADDRESSES=node-mcp=127.0.0.1:28687
export GRAPH_HTTP_ADDR=127.0.0.1:28443
export GRAPH_ADMIN_ADDR=127.0.0.1:29091
export GRAPH_INDEXER_ADMIN_ADDR=127.0.0.1:29092
export GRAPH_INDEXER_NOTIFY_URL=http://127.0.0.1:29092/v1/changes:process
export RUST_MIN_STACK=33554432

/usr/local/bin/graph-node > $ROOT/graph-node.log 2>&1 &
/usr/local/bin/graph-indexer > $ROOT/graph-indexer.log 2>&1 &

for i in $(seq 1 120); do
  if curl -sf http://127.0.0.1:29091/readyz >/dev/null && curl -sf http://127.0.0.1:29092/readyz >/dev/null; then
    echo "HydraDB ready after ${i}s"; break
  fi
  sleep 1
  if [ "$i" = 120 ]; then echo "HydraDB failed to start"; tail -30 $ROOT/graph-node.log; exit 1; fi
done

# Memory snapshot so we can see what the free tier is really using.
ps -eo rss,cmd | grep -E "graph-(node|indexer)" | grep -v grep | cut -c1-60 || true

python /app/hosted/restore_graph.py
exec python /app/hosted/server.py
