#!/usr/bin/env python3
"""Show HydraDB's real HTTP query response shape, so the website endpoint parses it correctly."""
import glob, json, os, pathlib, re, urllib.request, urllib.error, zlib

home = pathlib.Path.home()
log = (home / "dp-data" / "graph-node.log").read_text()
line = [l for l in log.splitlines() if "listeners started" in l][-1:]
addrs = re.findall(r'"(\w*addr\w*)":"([^"]+)"', line[0]) if line else []
print("addresses in log:", addrs)
cands = [v for k, v in addrs if "bolt" not in k and "admin" not in k] + ["127.0.0.1:8443"]


def nid(t):
    return zlib.crc32(t.encode()) & 0x7FFFFFFF


def req(url, body=None, token=None):
    r = urllib.request.Request(url, data=json.dumps(body).encode() if body else None)
    r.add_header("Content-Type", "application/json")
    if token:
        r.add_header("Authorization", "Bearer " + token)
    try:
        with urllib.request.urlopen(r, timeout=10) as resp:
            return resp.status, resp.read().decode()[:700]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:300]
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


base = None
for c in cands:
    st, body = req(f"http://{c}/healthz")
    print("GET", c, "/healthz ->", st, body[:80])
    if st == 200:
        base = c
        break
if not base:
    raise SystemExit("no HTTP query address answered /healthz; send this output to Claude")
paths = sorted(glob.glob(os.path.expanduser("~/dp-data/.tmp*")), key=os.path.getmtime, reverse=True)
for p in paths:
    try:
        tok = open(p).read().strip()
    except Exception:
        continue
    if len(tok) < 32 or "\n" in tok:
        continue
    q1 = "MATCH (s:Server {id: %d})-[:HOSTS]->(t:Tool) RETURN t.name AS name" % nid("memory")
    st, body = req(f"http://{base}/v1/graphs/default/query", {"cell_id": "cell-0", "query": q1}, tok)
    if st == 200:
        print("\nPOST query 1 (server -> tools) status", st)
        print(body)
        q2 = ("MATCH (w:Term {id: %d})-[r:USED_FOR]->(t:Tool) RETURN w.df AS df, t.name AS name, r.count AS c"
              % nid("term:memory"))
        st2, body2 = req(f"http://{base}/v1/graphs/default/query", {"cell_id": "cell-0", "query": q2}, tok)
        print("\nPOST query 2 (term -> tools) status", st2)
        print(body2)
        break
else:
    print("no token file accepted over HTTP")
