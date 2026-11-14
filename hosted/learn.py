"""Teach-it: write one new task->tools lesson into HydraDB, same edge forms as learn_graph.py."""
import json, threading
import traverse as tv
import learn_graph as lg
from learn_graph import nid, terms_of

LOCK = threading.Lock()
CAP = 200
DONE = [0]
IDS = {t["id"] for t in tv.catalog}


def tool_ids():
    return sorted(IDS)


def _ntasks():
    traces = [json.loads(l) for l in lg.TRACES.read_text().splitlines() if l.strip()]
    return lg.learn_counts(lg.last_valid(traces, "learn"))["n"]


NT = [_ntasks()]


def _ids(task):
    return [t["id"] for t in tv.sel.select(task, 5)[0]]


def teach(task, tools):
    task = str(task).strip()[:300]
    tools = list(dict.fromkeys(t for t in tools if t in IDS))[:8]
    if not task or not tools:
        raise ValueError("need a task and at least one valid tool")
    terms = sorted(terms_of(task))
    if not terms:
        raise ValueError("task has no usable words")
    with LOCK:
        if DONE[0] >= CAP:
            raise RuntimeError("teach limit reached for this instance")
        db = tv.db
        before = _ids(task)
        term_rows, used_rows, fol_rows = [], [], []
        for w in terms:
            rows = db.fetch_term(w)
            cur = {f"{r['server']}__{r['name']}": r["c"] for r in rows}
            term_rows.append({"vertex": nid("term:" + w), "name": w,
                              "df": (rows[0]["df"] if rows else 0) + 1, "ntasks": NT[0] + 1})
            for t in tools:
                used_rows.append({"source_vertex": nid("term:" + w), "destination_vertex": nid(t),
                                  "relationship_vertex": nid(f"{w}->{t}:USED_FOR"),
                                  "count": cur.get(t, 0) + 1})
        for a, b in {(x, y) for x, y in zip(tools, tools[1:]) if x != y}:
            cur = {f"{r['server']}__{r['name']}": r["c"] for r in db.fetch_follow(a)}
            fol_rows.append({"source_vertex": nid(a), "destination_vertex": nid(b),
                             "relationship_vertex": nid(f"{a}->{b}:FOLLOWS"),
                             "count": cur.get(b, 0) + 1})
        db.batches("UNWIND $rows AS row MERGE (n {id: row.vertex}) "
                   "SET n:Term, n.name = row.name, n.df = row.df, n.ntasks = row.ntasks", term_rows)
        db.batches("UNWIND $rows AS row MATCH (s:Term {id: row.source_vertex}), (d:Tool {id: row.destination_vertex}) "
                   "MERGE (s)-[r:USED_FOR {id: row.relationship_vertex}]->(d) SET r.count = row.count", used_rows)
        if fol_rows:
            db.batches("UNWIND $rows AS row MATCH (s:Tool {id: row.source_vertex}), (d:Tool {id: row.destination_vertex}) "
                       "MERGE (s)-[r:FOLLOWS {id: row.relationship_vertex}]->(d) SET r.count = row.count", fol_rows)
        NT[0] += 1
        DONE[0] += 1
        ntasks_ok = True
        try:
            db.run("MATCH (w:Term) SET w.ntasks = $n", n=NT[0])
        except Exception:
            ntasks_ok = False
        return {"task": task, "taught": tools, "terms": terms,
                "edges_written": {"USED_FOR": len(used_rows), "FOLLOWS": len(fol_rows)},
                "before": before, "after": _ids(task), "ntasks_updated": ntasks_ok,
                "note": "writes live in this instance's storage and reset on restart"}
