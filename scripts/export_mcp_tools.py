#!/usr/bin/env python3
"""Dump the tool list of any stdio MCP server to a JSON file for /connect.html.
Usage: python scripts/export_mcp_tools.py my_tools.json -- npx -y @modelcontextprotocol/server-filesystem /tmp
"""
import json, pathlib, queue, subprocess, sys, threading, time

if "--" not in sys.argv or len(sys.argv) < 4:
    sys.exit(__doc__)
out = pathlib.Path(sys.argv[1])
cmd = sys.argv[sys.argv.index("--") + 1:]
p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, bufsize=1)
q = queue.Queue()
threading.Thread(target=lambda: [q.put(l) for l in p.stdout], daemon=True).start()


def send(o):
    p.stdin.write(json.dumps(o) + "\n")
    p.stdin.flush()


def rpc(i, method, params, timeout=120):
    send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
    end = time.time() + timeout
    while time.time() < end:
        try:
            m = json.loads(q.get(timeout=1))
        except (queue.Empty, ValueError):
            continue
        if m.get("id") == i and "method" not in m:
            return m
    sys.exit("timed out waiting for " + method)


rpc(1, "initialize", {"protocolVersion": "2024-11-05", "capabilities": {}, "clientInfo": {"name": "desire-path-export", "version": "0.1"}})
send({"jsonrpc": "2.0", "method": "notifications/initialized"})
tools, cursor, n = [], None, 2
while True:
    m = rpc(n, "tools/list", {"cursor": cursor} if cursor else {})
    n += 1
    if "error" in m:
        sys.exit(json.dumps(m["error"]))
    r = m.get("result", {})
    tools += r.get("tools", [])
    cursor = r.get("nextCursor")
    if not cursor:
        break
p.kill()
out.write_text(json.dumps(tools, indent=1))
print(f"{len(tools)} tools written to {out}")
