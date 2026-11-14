#!/usr/bin/env python3
"""Continual-learning curve and ablations, offline (no LLM calls, no HydraDB).

For n learned traces (random order, many shuffles) it measures how many of the tools the real
agent needed on the held-out test tasks the selector offers (recall, as in offline_eval.py).
Selectors compared:
  graph        learned term->tool edges + one hop along FOLLOWS edges
  no-follow    same learned term->tool edges, WITHOUT the FOLLOWS hop (ablation)
  plain-store  tools used by the most similar past tasks (no graph structure)
  bm25         keyword search over tool text (no learning)
At n=0 every learned selector falls back to BM25, so the curve starts at the baseline.
This is an in-memory copy of the logic stored in HydraDB, not the HydraDB-backed run.
Writes results/learning_curve.json.  Usage: python scripts/learning_curve.py
"""
import json, math, pathlib, random, sys
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import learn_graph as lg
from run_agent import Bm25, load_catalog

SHUFFLES = 30
KS = (3, 5)


def sp(t):
    return t.split("__", 1)


def fetchers(counts, follow=True):
    def ft(w):
        if w not in counts["df"]:
            return []
        return [{"df": counts["df"][w], "ntasks": counts["n"], "server": sp(t)[0], "name": sp(t)[1], "c": c}
                for t, c in counts["cnt"][w].items()]

    def ff(t):
        if not follow:
            return []
        return [{"server": sp(b)[0], "name": sp(b)[1], "c": c} for b, c in counts["fol"][t].items()]
    return ft, ff


class PlainStore:
    """Past runs kept as a flat list; offer the tools of the most similar past tasks."""
    def __init__(self, traces, catalog, bm):
        self.bm, self.by_id = bm, {t["id"]: t for t in catalog}
        self.items = []
        for tr in traces:
            tools = []
            for c in lg.used_calls(tr):
                if c["tool"] not in tools:
                    tools.append(c["tool"])
            if tools:
                self.items.append({"terms": lg.terms_of(tr["prompt"]), "tools": tools})
        self.df = Counter()
        for it in self.items:
            self.df.update(it["terms"])

    def select(self, prompt, k):
        q, n = lg.terms_of(prompt), len(self.items)
        scored = []
        for it in self.items:
            s = sum(math.log(1 + n / self.df[w]) for w in q & it["terms"])
            if s > 0:
                scored.append((s, it))
        if not scored:
            return self.bm.top(prompt, k), {"fallback": True}
        scored.sort(key=lambda x: -x[0])
        chosen = []
        for _, it in scored:
            for t in it["tools"]:
                if t not in chosen and len(chosen) < k:
                    chosen.append(t)
            if len(chosen) >= k:
                break
        return [self.by_id[t] for t in chosen if t in self.by_id], {"fallback": False}


def score(sel_fn, tests, k, chars):
    rec, allf, tok = [], 0, []
    fam = defaultdict(list)
    for tr, need in tests:
        got, _ = sel_fn(tr["prompt"], k)
        ids = {t["id"] for t in got}
        r = len(need & ids) / len(need)
        rec.append(r)
        fam[tr["family"]].append(r)
        allf += need <= ids
        tok.append(sum(chars[i] for i in ids) // 4)
    n = len(tests)
    return sum(rec) / n, allf / n, sum(tok) / n, fam


def main():
    traces = [json.loads(l) for l in lg.TRACES.read_text().splitlines() if l.strip()]
    learn, test = lg.last_valid(traces, "learn"), lg.last_valid(traces, "test")
    catalog = load_catalog()
    ids = {t["id"] for t in catalog}
    chars = {t["id"]: t["chars"] for t in catalog}
    bm = Bm25(catalog)
    tests = []
    for tr in test:
        need = {c["tool"] for c in lg.used_calls(tr)} & ids
        if need:
            tests.append((tr, need))
    ns = sorted({n for n in (0, 2, 4, 6, 8, 12, 16, 20) if n <= len(learn)} | {len(learn)})
    print(f"{len(learn)} learn traces, {len(tests)} test tasks, {SHUFFLES} random orders; recall = share of needed tools offered")
    out = []
    final_fam = {}
    for k in KS:
        b_rec, b_all, b_tok, b_fam = score(lambda p, kk: (bm.top(p, kk), {}), tests, k, chars)
        for n in ns:
            agg = defaultdict(lambda: {"rec": [], "all": [], "tok": []})
            for seed in range(SHUFFLES):
                order = learn[:]
                random.Random(seed).shuffle(order)
                sub = order[:n]
                counts = lg.learn_counts(sub) if n else {"n": 0, "df": Counter(), "cnt": defaultdict(Counter), "fol": defaultdict(Counter)}
                sels = {
                    "graph": lg.Selector(*fetchers(counts, True), catalog, bm).select,
                    "no-follow": lg.Selector(*fetchers(counts, False), catalog, bm).select,
                    "plain-store": PlainStore(sub, catalog, bm).select,
                }
                for name, fn in sels.items():
                    r, a, t, fam = score(fn, tests, k, chars)
                    agg[name]["rec"].append(r)
                    agg[name]["all"].append(a)
                    agg[name]["tok"].append(t)
                    if n == ns[-1] and seed == 0:
                        final_fam[(k, name)] = fam
            cells = []
            for name in ("graph", "no-follow", "plain-store"):
                v = agg[name]
                m = sum(v["rec"]) / SHUFFLES
                cells.append(f"{name} {m:.2f}" + (f" ({min(v['rec']):.2f}-{max(v['rec']):.2f})" if name == "graph" else ""))
                out.append({"n": n, "k": k, "method": name, "recall": m, "recall_min": min(v["rec"]),
                            "recall_max": max(v["rec"]), "all_found": sum(v["all"]) / SHUFFLES,
                            "tokens": sum(v["tok"]) / SHUFFLES})
            out.append({"n": n, "k": k, "method": "bm25", "recall": b_rec, "all_found": b_all, "tokens": b_tok})
            allg = sum(agg["graph"]["all"]) / SHUFFLES
            print(f"k={k} n={n:>2} | recall: {' | '.join(cells)} | bm25 {b_rec:.2f} | graph all-found {allg:.2f}")
    k = KS[0]
    print(f"\nPer workflow family at n={ns[-1]}, k={k} (mean recall):")
    fams = sorted({f for f in final_fam[(k, 'graph')]})
    _, _, _, b_fam = score(lambda p, kk: (bm.top(p, kk), {}), tests, k, chars)
    for f in fams:
        row = [f"{name} {sum(final_fam[(k, name)][f]) / len(final_fam[(k, name)][f]):.2f}" for name in ("graph", "no-follow", "plain-store")]
        print(f"  {f:<9} " + " | ".join(row) + f" | bm25 {sum(b_fam[f]) / len(b_fam[f]):.2f}")
    lg.TRACES.parent.joinpath("learning_curve.json").write_text(json.dumps(out, indent=1))
    print("saved results/learning_curve.json")


if __name__ == "__main__":
    main()
