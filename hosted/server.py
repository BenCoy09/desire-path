"""Hosted app: static site + /select (live HydraDB routing) + /bench (capped load test)."""
import json, mimetypes, os, pathlib, threading, time
os.environ.setdefault("CACHE_TTL", "0")   # every request really traverses the graph
import common

common.patch()
import traverse as tv                      # connects to HydraDB, builds the selector
from concurrent.futures import ThreadPoolExecutor
from http.server import ThreadingHTTPServer
import learn, evalrun, accounts
EVAL_LOCK = threading.Lock()
from urllib.parse import urlparse, parse_qs

SITE = common.ROOT / "site"
PROMPTS = [t["prompt"] for t in tv.ra.TASKS if t["split"] == "test"]
BENCH_LOCK = threading.Lock()
LAST_BENCH = [0.0]
COOLDOWN = 30


def pct(a, p):
    a = sorted(a)
    return a[min(len(a) - 1, int(len(a) * p))] if a else 0


def run_bench():
    rows = []
    for c in (1, 5, 20):
        lat, errs = [], 0

        def one(i):
            t0 = time.perf_counter()
            try:
                tv.sel.select(PROMPTS[i % len(PROMPTS)], 5)
                return (time.perf_counter() - t0) * 1000, True
            except Exception:
                return 0, False

        t0 = time.perf_counter()
        with ThreadPoolExecutor(c) as ex:
            res = list(ex.map(one, range(100)))
        el = time.perf_counter() - t0
        lat = [r[0] for r in res if r[1]]
        rows.append({"concurrency": c, "requests": 100, "ok": len(lat), "errors": 100 - len(lat),
                     "rps": round(100 / el, 1), "p50_ms": round(pct(lat, .5), 1),
                     "p95_ms": round(pct(lat, .95), 1), "p99_ms": round(pct(lat, .99), 1)})
    return rows


FB = {"selects": 0, "fallbacks": 0}
_reply = tv.H.reply


def _fb_reply(self, code, obj):
    if isinstance(obj, dict) and "traversal_ms" in obj and "tools" in obj:
        FB["selects"] += 1
        if obj.get("no_confident_match"):
            FB["fallbacks"] += 1
            obj["fallback"] = "load_full_catalog"
            obj["catalog_size"] = len(tv.catalog)
    return _reply(self, code, obj)


tv.H.reply = _fb_reply


class Hosted(tv.H):
    def do_GET(self):
        u = urlparse(self.path)
        if accounts.handle(self, "GET", u.path, parse_qs(u.query), None):
            return
        if u.path in ("/select", "/health"):
            return super().do_GET()
        if u.path == "/status":
            return self.reply(200, dict(learn.status(), selects=FB["selects"], fallbacks=FB["fallbacks"]))
        if u.path == "/eval":
            if not EVAL_LOCK.acquire(blocking=False):
                return self.reply(429, {"error": "evaluation already running"})
            try:
                return self.reply(200, evalrun.run())
            except Exception as e:
                return self.reply(503, {"error": type(e).__name__ + " " + str(e)[:150]})
            finally:
                EVAL_LOCK.release()
        if u.path == "/tools":
            return self.reply(200, {"tools": learn.tool_ids()})
        if u.path == "/bench":
            return self.bench()
        if u.path == "/curve":
            return self.file(common.ROOT / "results" / "learning_curve.json")
        rel = "index.html" if u.path in ("", "/") else u.path.lstrip("/")
        p = (SITE / rel).resolve()
        if SITE.resolve() not in p.parents and p != SITE.resolve():
            return self.reply(404, {"error": "not found"})
        return self.file(p)

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length", 0))
            if n > 20000:
                raise ValueError("body too large")
            body = json.loads(self.rfile.read(n) or b"{}")
            path = urlparse(self.path).path
            if path != "/learn":
                return accounts.handle(self, "POST", path, {}, body) or self.reply(404, {"error": "not found"})
            return self.reply(200, learn.teach(body.get("task", ""), body.get("tools") or [], (self.headers.get("X-Forwarded-For", "").split(",")[0].strip() or self.client_address[0])))
        except ValueError as e:
            return self.reply(400, {"error": str(e)})
        except RuntimeError as e:
            return self.reply(429, {"error": str(e)})
        except Exception as e:
            return self.reply(503, {"error": "write failed: " + type(e).__name__ + " " + str(e)[:200]})

    def file(self, p):
        if not p.is_file():
            return self.reply(404, {"error": "not found"})
        b = p.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(p))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(b)))
        self.end_headers()
        self.wfile.write(b)

    def bench(self):
        if not BENCH_LOCK.acquire(blocking=False):
            return self.reply(429, {"error": "a benchmark is already running"})
        try:
            wait = COOLDOWN - (time.time() - LAST_BENCH[0])
            if wait > 0:
                return self.reply(429, {"error": f"try again in {int(wait) + 1}s"})
            rows = run_bench()
            LAST_BENCH[0] = time.time()
            return self.reply(200, {"rows": rows, "cache_ttl": tv.CACHE_TTL,
                                    "note": "every request traverses HydraDB (no cache)" if tv.CACHE_TTL <= 0 else "cache on"})
        finally:
            BENCH_LOCK.release()


class Server(ThreadingHTTPServer):
    request_queue_size = 256
    daemon_threads = True


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    print(f"serving on 0.0.0.0:{port}", flush=True)
    Server(("0.0.0.0", port), Hosted).serve_forever()
