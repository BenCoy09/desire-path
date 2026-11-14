#!/usr/bin/env python3
"""Usage: list_tools.py NAME -- COMMAND [ARGS...]"""
import json, subprocess, sys, pathlib, threading, queue

def main():
    if "--" not in sys.argv or len(sys.argv) < 4:
        sys.exit("usage: list_tools.py NAME -- COMMAND [ARGS...]")
    name = sys.argv[1]
    cmd = sys.argv[sys.argv.index("--") + 1:]
    out_dir = pathlib.Path(__file__).resolve().parent.parent / "data" / "tools"
    out_dir.mkdir(parents=True, exist_ok=True)
    p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                         stderr=subprocess.DEVNULL, text=True, bufsize=1)
    q = queue.Queue()
    threading.Thread(target=lambda: [q.put(l) for l in p.stdout], daemon=True).start()
    def send(o):
        p.stdin.write(json.dumps(o) + "\n"); p.stdin.flush()
    def wait_for(i, timeout=90):
        while True:
            try:
                m = json.loads(q.get(timeout=timeout))
            except ValueError:
                continue
            if m.get("id") == i:
                return m
    try:
        send({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "desire-path", "version": "0.1"}}})
        wait_for(1)
        send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        send({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = wait_for(2)["result"]["tools"]
    except Exception as e:
        print(f"FAILED {name}: {type(e).__name__}: {e}")
        p.kill(); sys.exit(1)
    p.kill()
    (out_dir / f"{name}.json").write_text(json.dumps(tools, indent=2))
    n = len(json.dumps(tools))
    print(f"{name}: {len(tools)} tools, {n} chars (~{n // 4} tokens, approximate)")
main()
