#!/usr/bin/env python3
"""traverse service. GET /select?task=...&k=5 -> selected tools + traversal_ms. No LLM calls."""
import json, pathlib, sys, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_agent as ra
import learn_graph as lg

catalog = ra.load_catalog()
db = lg.Hydra()
import os
CACHE_TTL = float(os.environ.get("CACHE_TTL", "60"))

def cached(fn):
    store = {}
    def w(key):
        if CACHE_TTL <= 0:
            return fn(key)
        now = time.monotonic()
        hit = store.get(key)
        if hit and now - hit[0] < CACHE_TTL:
            return hit[1]
        v = fn(key)
        store[key] = (now, v)
        return v
    return w

sel = lg.Selector(cached(db.fetch_term), cached(db.fetch_follow), catalog, ra.Bm25(catalog))

class H(BaseHTTPRequestHandler):
    def reply(self, code, obj):
        b = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def do_GET(self):
        u = urlparse(self.path)
        q = parse_qs(u.query)
        if u.path == "/health":
            return self.reply(200, {"ok": True, "tools": len(catalog)})
        if u.path != "/select":
            return self.reply(404, {"error": "not found"})
        task = q.get("task", [""])[0].strip()
        if not task:
            return self.reply(400, {"error": "task is required"})
        try:
            k = max(1, min(int(q.get("k", ["5"])[0]), 20))
        except ValueError:
            return self.reply(400, {"error": "k must be an integer"})
        t0 = time.perf_counter()
        try:
            tools, info = sel.select(task, k)
        except Exception as e:
            return self.reply(503, {"error": "graph unavailable: " + type(e).__name__})
        ms = round((time.perf_counter() - t0) * 1000, 1)
        self.reply(200, {"tools": [{"name": t["name"], "server": t.get("server")} for t in tools],
                         "info": info, "traversal_ms": ms})

    def log_message(self, *a):
        pass

if __name__ == "__main__":
    print("traverse on http://127.0.0.1:8099")
    class S(ThreadingHTTPServer):
        request_queue_size = 256
    S(("127.0.0.1", 8099), H).serve_forever()
