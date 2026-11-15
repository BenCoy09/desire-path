#!/usr/bin/env python3
"""Does the graph's tool ordering help? Offline, no LLM calls.
Selectors: plain store | graph w/o sequence edges | graph forward edges (current) | graph + predecessor edges."""
import json, math, pathlib, sys
from collections import Counter, defaultdict
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import learn_graph as lg
from learning_curve import fetchers, PlainStore
from run_agent import Bm25, load_catalog
try:
    from learning_curve import sp
except ImportError:
    sp = lambda t: t.split("__", 1)

class Pred(lg.Selector):
    def __init__(self, ft, ff, fp, catalog, bm):
        super().__init__(ft, ff, catalog, bm); self.fp = fp
    def select(self, prompt, k=5):
        scores, known = Counter(), 0
        for w in sorted(lg.terms_of(prompt)):
            rows = self.fetch_term(w)
            if not rows: continue
            known += 1
            tot = sum(r["c"] for r in rows) or 1
            idf = math.log(1 + rows[0]["ntasks"] / max(1, rows[0]["df"]))
            for r in rows: scores[f"{r['server']}__{r['name']}"] += idf * r["c"] / tot
        info = {"known_terms": known, "fallback": False}
        if not scores:
            info["fallback"] = True; return self.bm25.top(prompt, k), info
        ranked = [t for t, _ in scores.most_common()]
        chosen = ranked[:min(3, k)]
        for seed in list(chosen):
            for fn in (self.fetch_follow, self.fp):
                rows = fn(seed); tot = sum(r["c"] for r in rows) or 1
                for r in sorted(rows, key=lambda r: -r["c"]):
                    tid = f"{r['server']}__{r['name']}"
                    if len(chosen) < k and tid not in chosen and tid in self.by_id and r["c"] / tot >= 0.25:
                        chosen.append(tid)
        for t in ranked:
            if len(chosen) >= k: break
            if t not in chosen: chosen.append(t)
        return [self.by_id[t] for t in chosen if t in self.by_id], info

traces = [json.loads(l) for l in lg.TRACES.read_text().splitlines() if l.strip()]
allt = {}
for r in traces:
    if r["method"] == "preload" and not r.get("error") and r["success"]: allt[r["task_id"]] = r
allt = list(allt.values())
catalog = load_catalog(); ids = {t["id"] for t in catalog}; chars = {t["id"]: t["chars"] for t in catalog}
bm = Bm25(catalog)
cd = next((i for i in ids if i.endswith("__create_directory")), None)
fams = sorted({t["family"] for t in allt})
loto = [([t], [x for x in allt if x is not t]) for t in allt]
lofo = [([t for t in allt if t["family"] == f], [t for t in allt if t["family"] != f]) for f in fams]
NAMES = ["plain-store", "graph, no sequence edges", "graph, forward edges (now)", "graph + predecessor edges"]

def run(folds, k):
    res = {n: {"rec": [], "all": [], "tok": [], "cd": []} for n in NAMES}
    for held, rest in folds:
        counts = lg.learn_counts(rest)
        ft, ff = fetchers(counts, True); ft0, ff0 = fetchers(counts, False)
        inc = defaultdict(Counter)
        for a in counts["fol"]:
            for b, c in counts["fol"][a].items(): inc[b][a] = c
        fp = lambda t: [{"server": sp(a)[0], "name": sp(a)[1], "c": c} for a, c in inc[t].items()]
        sels = {NAMES[0]: PlainStore(rest, catalog, bm).select, NAMES[1]: lg.Selector(ft0, ff0, catalog, bm).select,
                NAMES[2]: lg.Selector(ft, ff, catalog, bm).select, NAMES[3]: Pred(ft, ff, fp, catalog, bm).select}
        for tr in held:
            need = {c["tool"] for c in lg.used_calls(tr)} & ids
            if not need: continue
            for n, fn in sels.items():
                got, _ = fn(tr["prompt"], k); off = {t["id"] for t in got}
                res[n]["rec"].append(len(need & off) / len(need)); res[n]["all"].append(need <= off)
                res[n]["tok"].append(sum(chars[i] for i in off) // 4)
                if cd and cd in need: res[n]["cd"].append(cd in off)
    return res

print(f"{len(allt)} traces, {len(fams)} families. create_directory id: {cd}")
for k in (4, 5):
    for title, folds in (("LEAVE-ONE-TASK-OUT (new instance)", loto), ("LEAVE-ONE-FAMILY-OUT (new kind of work)", lofo)):
        r = run(folds, k); n = len(r[NAMES[0]]["rec"])
        print(f"\n{title}, k={k}, n={n}")
        for name in NAMES:
            x = r[name]; cdn = len(x["cd"])
            print(f"  {name:<28} recall {sum(x['rec'])/n:.2f}  all-found {sum(x['all'])/n:.2f}  ~{sum(x['tok'])//n} tok  | create_directory offered {sum(x['cd'])}/{cdn}")
