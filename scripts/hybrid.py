#!/usr/bin/env python3
"""Hybrid selector: learned term->tool evidence blended with a BM25 keyword score.

Why: on new kinds of work the learned graph knows no matching words and offers wrong tools,
while keyword search can still match tool descriptions (e.g. 'move' -> move_file).
score(tool) = learned/max_learned + lam * bm25/max_bm25, then the same one-hop FOLLOWS expansion.
lam=0 is the original graph selector. Offline, no LLM calls, no HydraDB (same in-memory logic).
Usage: python scripts/hybrid.py      (evaluates a small grid of lam on all 30 traces)
Note: lam is chosen by looking at these same 30 tasks, so treat the best row as optimistic.
"""
import math, pathlib, sys, json
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import learn_graph as lg
from learning_curve import fetchers, PlainStore
from run_agent import Bm25, load_catalog, toks

LAMS = (0.0, 0.25, 0.5, 1.0, 2.0)
KS = (3, 5)


def bm25_scores(bm, query):
    out = {}
    for i, t in enumerate(bm.cat):
        tf = Counter(bm.docs[i])
        sc = 0.0
        for w in toks(query):
            if w in tf:
                idf = math.log(1 + (bm.N - bm.df[w] + 0.5) / (bm.df[w] + 0.5))
                sc += idf * tf[w] * 2.5 / (tf[w] + 1.5 * (0.25 + 0.75 * len(bm.docs[i]) / bm.avgdl))
        out[t["id"]] = sc
    return out


class Hybrid:
    def __init__(self, fetch_term, fetch_follow, catalog, bm, lam=0.5):
        self.fetch_term, self.fetch_follow, self.bm, self.lam = fetch_term, fetch_follow, bm, lam
        self.by_id = {t["id"]: t for t in catalog}

    def learned(self, prompt):
        scores, known = Counter(), 0
        for w in sorted(lg.terms_of(prompt)):
            rows = self.fetch_term(w)
            if not rows:
                continue
            known += 1
            tot = sum(r["c"] for r in rows) or 1
            idf = math.log(1 + rows[0]["ntasks"] / max(1, rows[0]["df"]))
            for r in rows:
                scores[f"{r['server']}__{r['name']}"] += idf * r["c"] / tot
        return scores, known

    def select(self, prompt, k=5):
        L, known = self.learned(prompt)
        B = bm25_scores(self.bm, prompt)
        mL = max(L.values()) if L else 0.0
        mB = max(B.values()) if B else 0.0
        info = {"known_terms": known, "fallback": False}
        if mL == 0 and mB == 0:
            info["fallback"] = True
            return self.bm.top(prompt, k), info
        comb = {t: (L.get(t, 0) / mL if mL else 0.0) + self.lam * (B.get(t, 0) / mB if mB else 0.0)
                for t in self.by_id}
        ranked = sorted(comb, key=lambda t: -comb[t])
        chosen = ranked[:min(3, k)]
        for seed in list(chosen):
            rows = self.fetch_follow(seed)
            tot = sum(r["c"] for r in rows) or 1
            for r in sorted(rows, key=lambda r: -r["c"]):
                tid = f"{r['server']}__{r['name']}"
                if len(chosen) < k and tid not in chosen and tid in self.by_id and r["c"] / tot >= 0.25:
                    chosen.append(tid)
        for t in ranked:
            if len(chosen) >= k:
                break
            if t not in chosen:
                chosen.append(t)
        return [self.by_id[t] for t in chosen], info


def run_mode(folds, catalog, ids, chars, bm, k):
    pool = {lam: [] for lam in LAMS}
    pool["plain"], pool["bm25"] = [], []
    fam = {lam: defaultdict(list) for lam in LAMS}
    fam["bm25"] = defaultdict(list)
    for held, rest in folds:
        counts = lg.learn_counts(rest)
        ft, ff = fetchers(counts, True)
        hs = {lam: Hybrid(ft, ff, catalog, bm, lam) for lam in LAMS}
        plain = PlainStore(rest, catalog, bm)
        for tr in held:
            need = {c["tool"] for c in lg.used_calls(tr)} & ids
            if not need:
                continue

            def rec(fn):
                got, _ = fn(tr["prompt"], k)
                off = {t["id"] for t in got}
                return len(need & off) / len(need), need <= off, sum(chars[i] for i in off) // 4

            for lam, h in hs.items():
                r = rec(h.select)
                pool[lam].append(r)
                fam[lam][tr["family"]].append(r[0])
            pool["plain"].append(rec(plain.select))
            r = rec(lambda p, kk: (bm.top(p, kk), {}))
            pool["bm25"].append(r)
            fam["bm25"][tr["family"]].append(r[0])
    return pool, fam


def show(pool):
    for key in list(LAMS) + ["plain", "bm25"]:
        rows = pool[key]
        n = len(rows)
        name = f"hybrid lam={key}" if key in LAMS else {"plain": "plain-store", "bm25": "bm25"}[key]
        if key == 0.0:
            name = "graph only (lam=0)"
        print(f"  {name:<20} recall {sum(r[0] for r in rows) / n:.2f}  all-found {sum(r[1] for r in rows) / n:.2f}"
              f"  ~{sum(r[2] for r in rows) / n:.0f} tok")


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
    print(f"{len(allt)} traces, {len(fams)} families. lam is tuned on these same tasks (optimistic).")
    loto = [([t], [x for x in allt if x is not t]) for t in allt]
    lofo = [([t for t in allt if t["family"] == f], [t for t in allt if t["family"] != f]) for f in fams]
    for k in KS:
        for title, folds in (("LEAVE-ONE-TASK-OUT (new instance)", loto), ("LEAVE-ONE-FAMILY-OUT (new kind of work)", lofo)):
            pool, fam = run_mode(folds, catalog, ids, chars, bm, k)
            print(f"\n{title}, k={k}, n={len(pool['bm25'])}")
            show(pool)
            if k == KS[-1] and "FAMILY" in title:
                print("  per family recall at k=%d: " % k + " | ".join(
                    f"lam{l}" for l in LAMS) + " | bm25")
                for f in fams:
                    cells = [f"{sum(fam[l][f]) / max(1, len(fam[l][f])):.2f}" for l in list(LAMS) + ["bm25"]]
                    print(f"    {f:<9} " + " ".join(cells))


if __name__ == "__main__":
    main()
