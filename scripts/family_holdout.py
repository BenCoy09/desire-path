#!/usr/bin/env python3
"""Bigger, free generalization check using ALL successful preload traces (learn + test = 30 tasks).
Offline, no LLM calls, no HydraDB (same in-memory logic as learning_curve.py).

  leave-one-task-out    learn from the other tasks, test on the one left out
                        (a new instance of a workflow the graph has seen)
  leave-one-family-out  learn from every OTHER workflow family, test on the left-out family
                        (a new KIND of work: the hard case)
recall = share of the tools the real agent needed that the selector offered.
Usage: python scripts/family_holdout.py
"""
import json, pathlib, sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import learn_graph as lg
from learning_curve import fetchers, PlainStore
from run_agent import Bm25, load_catalog

KS = (3, 5)


def evaluate(held, rest, catalog, ids, chars, bm, k):
    counts = lg.learn_counts(rest)
    sels = {
        "graph": lg.Selector(*fetchers(counts, True), catalog, bm).select,
        "no-follow": lg.Selector(*fetchers(counts, False), catalog, bm).select,
        "plain-store": PlainStore(rest, catalog, bm).select,
        "bm25": lambda p, kk: (bm.top(p, kk), {}),
    }
    res = {name: [] for name in sels}
    for tr in held:
        need = {c["tool"] for c in lg.used_calls(tr)} & ids
        if not need:
            continue
        for name, fn in sels.items():
            got, _ = fn(tr["prompt"], k)
            offered = {t["id"] for t in got}
            res[name].append((len(need & offered) / len(need), need <= offered,
                              sum(chars[i] for i in offered) // 4))
    return res


def summarize(pool):
    line = []
    for name in ("graph", "no-follow", "plain-store", "bm25"):
        rows = pool[name]
        n = len(rows)
        line.append(f"{name} recall {sum(r[0] for r in rows) / n:.2f} all-found {sum(r[1] for r in rows) / n:.2f}"
                    f" ~{sum(r[2] for r in rows) / n:.0f}tok")
    return " | ".join(line), len(pool["graph"])


def main():
    traces = [json.loads(l) for l in lg.TRACES.read_text().splitlines() if l.strip()]
    allt = {}
    for r in traces:
        if r["method"] == "preload" and not r.get("error") and r["success"]:
            allt[r["task_id"]] = r
    allt = list(allt.values())
    catalog = load_catalog()
    ids = {t["id"] for t in catalog}
    chars = {t["id"]: t["chars"] for t in catalog}
    bm = Bm25(catalog)
    fams = sorted({t["family"] for t in allt})
    print(f"{len(allt)} successful preload traces, {len(fams)} workflow families")
    for k in KS:
        pool = {n: [] for n in ("graph", "no-follow", "plain-store", "bm25")}
        for t in allt:
            res = evaluate([t], [x for x in allt if x is not t], catalog, ids, chars, bm, k)
            for n in pool:
                pool[n] += res[n]
        s, n = summarize(pool)
        print(f"\nLEAVE-ONE-TASK-OUT (new instance of a known workflow), n={n}, k={k}\n  {s}")
    for k in KS:
        pool = {n: [] for n in ("graph", "no-follow", "plain-store", "bm25")}
        per = {}
        for f in fams:
            held = [t for t in allt if t["family"] == f]
            res = evaluate(held, [t for t in allt if t["family"] != f], catalog, ids, chars, bm, k)
            per[f] = res
            for n in pool:
                pool[n] += res[n]
        s, n = summarize(pool)
        print(f"\nLEAVE-ONE-FAMILY-OUT (new KIND of work), n={n}, k={k}\n  {s}")
        if k == KS[-1]:
            print("  per family recall (graph / plain-store / bm25):")
            for f in fams:
                g = per[f]
                print(f"    {f:<9} " + " / ".join(
                    f"{sum(r[0] for r in g[nm]) / max(1, len(g[nm])):.2f}" for nm in ("graph", "plain-store", "bm25")))


if __name__ == "__main__":
    main()
