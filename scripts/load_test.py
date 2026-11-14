import sys, time, json, pathlib, urllib.request, urllib.parse
from concurrent.futures import ThreadPoolExecutor
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_agent as ra
P = [t["prompt"] for t in ra.TASKS if t["split"] == "test"]
def call(i):
    u = "http://127.0.0.1:8099/select?" + urllib.parse.urlencode({"task": P[i % len(P)], "k": 5})
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(u, timeout=30) as r:
            d = json.loads(r.read())
        return (time.perf_counter() - t0) * 1000, d["traversal_ms"], True
    except Exception:
        return 0, 0, False
def pct(a, p): a = sorted(a); return a[min(len(a) - 1, int(len(a) * p))]
first = call(0)
print(f"first request (cold only if traverse was just restarted): {first[0]:.0f} ms")
print(f'{"conc":>5}{"ok":>6}{"rps":>7}{"p50":>7}{"p95":>7}{"p99":>7}{"srv p95":>9}')
for c in (1, 5, 20, 50):
    t0 = time.perf_counter()
    with ThreadPoolExecutor(c) as ex:
        res = list(ex.map(call, range(200)))
    el = time.perf_counter() - t0
    ok = [r for r in res if r[2]]
    lat = [r[0] for r in ok] or [0]; srv = [r[1] for r in ok] or [0]
    print(f"{c:>5}{len(ok):>6}{200/el:>7.1f}{pct(lat,.5):>7.0f}{pct(lat,.95):>7.0f}{pct(lat,.99):>7.0f}{pct(srv,.95):>9.0f}")
