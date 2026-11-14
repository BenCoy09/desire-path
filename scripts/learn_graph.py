#!/usr/bin/env python3
"""Learn a task->tool graph in HydraDB from successful preload traces, then
evaluate retrieval OFFLINE on held-out test tasks (no LLM calls).

Learning uses ONLY successful preload traces on the learn split.
Slice filter: a successful call is kept only if it changed state, or its output
was later used (by a kept call's arguments or the final answer). Exploration
whose output nobody used is dropped, so the graph does not learn detours.
Graph written to HydraDB:
  (:Term)-[:USED_FOR {count}]->(:Tool)   task words -> tools that were needed
  (:Tool)-[:FOLLOWS  {count}]->(:Tool)   tool B directly after tool A in kept calls
Offline metric: of the tools the real preload agent needed on each test task
(after the slice), how many did the selector include, at what token cost.
Usage: python scripts/learn_graph.py [--no-write]
"""
import argparse, glob, json, math, os, pathlib, re, sys, zlib
from collections import Counter, defaultdict

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from run_agent import Bm25, load_catalog, SYSTEM  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parent.parent
TRACES = ROOT / "results" / "traces.jsonl"
MUT = ("write", "edit", "move", "create", "add_", "delete", "append", "copy")
STOP = set("""the and for with that this from into then tell what which who how about its his her all
any each one two both only not are was can you your please just also some there them they been have has
had will would should could does did done make get use using give put out off per via than too very own
same other such more most less least many much here when where why whose whom these those""".split())
ATOM_STOP = STOP | {"true", "false", "null", "none", "text", "type", "content", "error",
                    "file", "files", "directory", "directories", "folder"}


def nid(text):
    return zlib.crc32(text.encode()) & 0x7FFFFFFF


def terms_of(prompt):
    return {w for w in re.findall(r"[a-z0-9]{3,}", prompt.lower()) if w not in STOP}


def atoms(text):
    return {a for a in re.findall(r"[a-z0-9]{3,}", (text or "").lower()) if a not in ATOM_STOP}


def used_calls(tr):
    """Backward slice over one trace; returns kept calls in original order."""
    base = atoms(tr["prompt"]) | atoms(SYSTEM)
    needed = atoms(tr.get("final", "")) - base
    keep = []
    for c in reversed(tr["calls"]):
        if c["error"]:
            continue
        name = c["tool"].split("__", 1)[-1]
        if name.startswith(MUT) or (atoms(c["result"]) & needed):
            keep.append(c)
            needed |= atoms(json.dumps(c["args"])) - base
    keep.reverse()
    return keep


def learn_counts(traces):
    out = {"n": 0, "df": Counter(), "cnt": defaultdict(Counter), "fol": defaultdict(Counter),
           "kept": 0, "total": 0, "dropped": Counter(), "skipped": 0}
    for tr in traces:
        ok = [c for c in tr["calls"] if not c["error"]]
        keep = used_calls(tr)
        kept_idx = {c["idx"] for c in keep}
        out["total"] += len(ok)
        out["kept"] += len(keep)
        for c in ok:
            if c["idx"] not in kept_idx:
                out["dropped"][c["tool"]] += 1
        tools = [c["tool"] for c in keep]
        if not tools:
            out["skipped"] += 1
            continue
        out["n"] += 1
        for w in terms_of(tr["prompt"]):
            out["df"][w] += 1
            for t in set(tools):
                out["cnt"][w][t] += 1
        for a, b in set(zip(tools, tools[1:])):
            if a != b:
                out["fol"][a][b] += 1
    return out


class Selector:
    def __init__(self, fetch_term, fetch_follow, catalog, bm25):
        self.fetch_term, self.fetch_follow, self.bm25 = fetch_term, fetch_follow, bm25
        self.by_id = {t["id"]: t for t in catalog}

    def select(self, prompt, k=5):
        scores, known = Counter(), 0
        for w in sorted(terms_of(prompt)):
            rows = self.fetch_term(w)
            if not rows:
                continue
            known += 1
            tot = sum(r["c"] for r in rows) or 1
            idf = math.log(1 + rows[0]["ntasks"] / max(1, rows[0]["df"]))
            for r in rows:
                scores[f"{r['server']}__{r['name']}"] += idf * r["c"] / tot
        info = {"known_terms": known, "fallback": False}
        if not scores:
            info["fallback"] = True
            return self.bm25.top(prompt, k), info
        ranked = [t for t, _ in scores.most_common()]
        chosen = ranked[:min(3, k)]
        for seed in list(chosen):                      # one hop along FOLLOWS edges
            rows = self.fetch_follow(seed)
            tot = sum(r["c"] for r in rows) or 1
            for r in sorted(rows, key=lambda r: -r["c"]):
                tid = f"{r['server']}__{r['name']}"
                if len(chosen) < k and tid not in chosen and r["c"] / tot >= 0.25:
                    chosen.append(tid)
        for t in ranked:
            if len(chosen) >= k:
                break
            if t not in chosen:
                chosen.append(t)
        return [self.by_id[t] for t in chosen if t in self.by_id], info


# ------------------------------------------------------------ HydraDB access
def connect():
    from neo4j import GraphDatabase
    addr = "127.0.0.1:28687"
    try:
        log = (pathlib.Path.home() / "dp-data" / "graph-node.log").read_text()
        found = re.findall(r'"bolt_addr":"([^"]+)"', log)
        if found:
            addr = found[-1]
    except OSError:
        pass
    paths = sorted(glob.glob(os.path.expanduser("~/dp-data/.tmp*")), key=os.path.getmtime, reverse=True)
    for p in paths:
        try:
            tok = open(p).read().strip()
            if len(tok) < 32 or "\n" in tok:
                continue
            d = GraphDatabase.driver(f"bolt://{addr}", auth=("neo4j", tok))
            d.verify_connectivity()
            print("connected to HydraDB at", addr)
            return d
        except Exception:
            continue
    sys.exit("could not connect to HydraDB: is `just mcp-local /home/hpbenny/dp-data` running?")


class Hydra:
    def __init__(self):
        self.d = connect()

    def run(self, cy, **params):
        with self.d.session(database="default") as s:
            return [r.data() for r in s.run(cy, **params)]

    def batches(self, cy, rows, size=150):
        for i in range(0, len(rows), size):
            with self.d.session(database="default") as s:
                s.run(cy, rows=rows[i:i + size]).consume()

    def write(self, counts, catalog_ids):
        n = counts["n"]
        reserved = {nid(t) for t in catalog_ids}
        term_rows, used_rows, fol_rows = [], [], []
        for w, df in counts["df"].items():
            term_rows.append({"vertex": nid("term:" + w), "name": w, "df": df, "ntasks": n})
            for t, c in counts["cnt"][w].items():
                if t in catalog_ids:
                    used_rows.append({"source_vertex": nid("term:" + w), "destination_vertex": nid(t),
                                      "relationship_vertex": nid(f"{w}->{t}:USED_FOR"), "count": c})
        for a, bs in counts["fol"].items():
            for b, c in bs.items():
                if a in catalog_ids and b in catalog_ids:
                    fol_rows.append({"source_vertex": nid(a), "destination_vertex": nid(b),
                                     "relationship_vertex": nid(f"{a}->{b}:FOLLOWS"), "count": c})
        tids = [r["vertex"] for r in term_rows]
        if len(set(tids)) != len(tids) or reserved & set(tids):
            sys.exit("id collision among term nodes; tell Claude")
        eids = [r["relationship_vertex"] for r in used_rows + fol_rows]
        if len(set(eids)) != len(eids):
            sys.exit("id collision among edges; tell Claude")
        self.batches("UNWIND $rows AS row MERGE (n {id: row.vertex}) "
                     "SET n:Term, n.name = row.name, n.df = row.df, n.ntasks = row.ntasks", term_rows)
        print(f"wrote {len(term_rows)} Term nodes")
        self.batches("UNWIND $rows AS row MATCH (s:Term {id: row.source_vertex}), (d:Tool {id: row.destination_vertex}) "
                     "MERGE (s)-[r:USED_FOR {id: row.relationship_vertex}]->(d) SET r.count = row.count", used_rows)
        print(f"wrote {len(used_rows)} USED_FOR edges")
        self.batches("UNWIND $rows AS row MATCH (s:Tool {id: row.source_vertex}), (d:Tool {id: row.destination_vertex}) "
                     "MERGE (s)-[r:FOLLOWS {id: row.relationship_vertex}]->(d) SET r.count = row.count", fol_rows)
        print(f"wrote {len(fol_rows)} FOLLOWS edges")

    def fetch_term(self, w):
        return self.run("MATCH (w:Term {id: %d})-[r:USED_FOR]->(t:Tool) RETURN w.df AS df, "
                        "w.ntasks AS ntasks, t.server AS server, t.name AS name, r.count AS c" % nid("term:" + w))

    def fetch_follow(self, tool_id):
        return self.run("MATCH (a:Tool {id: %d})-[r:FOLLOWS]->(b:Tool) RETURN b.server AS server, "
                        "b.name AS name, r.count AS c" % nid(tool_id))


# ------------------------------------------------------------ evaluation
def evaluate(selector, bm, catalog, tests, ks):
    chars = {t["id"]: t["chars"] for t in catalog}
    print(f"preload all {len(catalog)} tools: recall 1.00, ~{sum(chars.values()) // 4} tokens of definitions per call")
    misses = []
    for k in ks:
        line = [f"k={k}"]
        for name in ("graph", "bm25"):
            rec, allf, tok, fb = [], 0, [], 0
            for tr, need in tests:
                if name == "graph":
                    sel, info = selector.select(tr["prompt"], k)
                    fb += info["fallback"]
                else:
                    sel = bm.top(tr["prompt"], k)
                ids = {t["id"] for t in sel}
                rec.append(len(need & ids) / len(need))
                allf += need <= ids
                tok.append(sum(chars[i] for i in ids) // 4)
                if name == "graph" and k == 5 and not need <= ids:
                    misses.append(f"  {tr['task_id']} needs {sorted(need - ids)}")
            n = len(tests)
            extra = f", fallbacks {fb}" if name == "graph" else ""
            line.append(f"{name}: recall {sum(rec) / n:.2f} all-found {allf / n:.2f} ~{sum(tok) / n:.0f} tok{extra}")
        print(" | ".join(line))
    if misses:
        print("graph misses at k=5:")
        print("\n".join(misses))


def last_valid(traces, split):
    d = {}
    for r in traces:
        if r["method"] == "preload" and r["split"] == split and not r.get("error") and r["success"]:
            d[r["task_id"]] = r
    return list(d.values())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    a = ap.parse_args()
    traces = [json.loads(l) for l in TRACES.read_text().splitlines() if l.strip()]
    learn, test = last_valid(traces, "learn"), last_valid(traces, "test")
    print(f"successful preload traces: learn {len(learn)}, test {len(test)}")
    assert not ({t["task_id"] for t in learn} & {t["task_id"] for t in test}), "split leak"
    counts = learn_counts(learn)
    print(f"learned from {counts['n']} traces ({counts['skipped']} had nothing to learn); "
          f"slice kept {counts['kept']} of {counts['total']} successful calls")
    print("dropped as unused exploration:", dict(counts["dropped"].most_common(6)))
    catalog = load_catalog()
    ids = {t["id"] for t in catalog}
    unknown = {t for c in counts["cnt"].values() for t in c} - ids
    if unknown:
        print("note: tools in traces but not in catalog (ignored):", sorted(unknown))
    db = Hydra()
    if not a.no_write:
        db.write(counts, ids)
    bm = Bm25(catalog)
    sel = Selector(db.fetch_term, db.fetch_follow, catalog, bm)
    tests = []
    for tr in test:
        need = {c["tool"] for c in used_calls(tr)} & ids
        if need:
            tests.append((tr, need))
    print(f"evaluating on {len(tests)} held-out test tasks (tools the real agent needed, after slice)")
    evaluate(sel, bm, catalog, tests, (3, 4, 5, 6, 8))


if __name__ == "__main__":
    main()
