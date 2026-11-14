#!/usr/bin/env python3
"""Export the learned graph from HydraDB to site/graph.json for the static site."""
import json, pathlib, sys, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_agent as ra
import learn_graph as lg

catalog = ra.load_catalog()
db = lg.Hydra()
sel = lg.Selector(db.fetch_term, db.fetch_follow, catalog, ra.Bm25(catalog))
words = set()
for t in ra.TASKS:
    words |= lg.terms_of(t["prompt"])
terms = {}
for w in sorted(words):
    rows = db.fetch_term(w)
    if rows:
        terms[w] = {"df": rows[0]["df"], "ntasks": rows[0]["ntasks"],
                    "rows": [[f'{r["server"]}__{r["name"]}', r["c"]] for r in rows]}
follow = {}
for t in catalog:
    rows = db.fetch_follow(t["id"])
    if rows:
        follow[t["id"]] = [[f'{r["server"]}__{r["name"]}', r["c"]] for r in rows]
tools = [{"id": t["id"], "name": t["name"], "server": t.get("server"), "chars": t["chars"]} for t in catalog]
expected = []
for t in ra.TASKS:
    if t["split"] == "test":
        chosen, info = sel.select(t["prompt"], 5)
        expected.append({"id": t["id"], "prompt": t["prompt"], "tools": [x["id"] for x in chosen], "fallback": info["fallback"]})
out = {"generated": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()), "stop": sorted(lg.STOP),
       "tools": tools, "terms": terms, "follow": follow, "expected": expected}
pathlib.Path("site/graph.json").write_text(json.dumps(out))
print(f"tools={len(tools)} terms={len(terms)} term_edges={sum(len(v['rows']) for v in terms.values())} follow_edges={sum(len(v) for v in follow.values())} expected={len(expected)}")
