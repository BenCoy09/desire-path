#!/usr/bin/env python3
"""Offline check WITHOUT HydraDB: same learning + retrieval logic, counts held in memory.
This answers 'does learning from traces help?' It is NOT the HydraDB-backed run."""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import learn_graph as lg
from run_agent import Bm25, load_catalog

traces = [json.loads(l) for l in lg.TRACES.read_text().splitlines() if l.strip()]
learn, test = lg.last_valid(traces, "learn"), lg.last_valid(traces, "test")
counts = lg.learn_counts(learn)
catalog = load_catalog()
ids = {t["id"] for t in catalog}


def sp(t):
    return t.split("__", 1)


def fetch_term(w):
    if w not in counts["df"]:
        return []
    return [{"df": counts["df"][w], "ntasks": counts["n"], "server": sp(t)[0], "name": sp(t)[1], "c": c}
            for t, c in counts["cnt"][w].items()]


def fetch_follow(t):
    return [{"server": sp(b)[0], "name": sp(b)[1], "c": c} for b, c in counts["fol"][t].items()]


bm = Bm25(catalog)
sel = lg.Selector(fetch_term, fetch_follow, catalog, bm)
tests = []
for tr in test:
    need = {c["tool"] for c in lg.used_calls(tr)} & ids
    if need:
        tests.append((tr, need))
print(f"IN-MEMORY check (not HydraDB): learned from {counts['n']} traces, {len(tests)} held-out test tasks")
lg.evaluate(sel, bm, catalog, tests, (3, 4, 5, 6, 8))
