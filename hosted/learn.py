"""Lesson writer shared by live /learn and the startup journal replay."""
import json, os, pathlib, threading, time
import learn_graph as lg
from learn_graph import nid, terms_of
import journal

LOCK = threading.Lock()
HITS = {}
CAP = 500
STATE = {"nt": None, "replayed": 0, "taught": 0}


def base_ntasks():
    traces = [json.loads(l) for l in lg.TRACES.read_text().splitlines() if l.strip()]
    return lg.learn_counts(lg.last_valid(traces, "learn"))["n"]


def clean(task, tools, ids):
    task = str(task).strip()[:300]
    tools = list(dict.fromkeys(t for t in tools if t in ids))[:8]
    if not task or not tools:
        raise ValueError("need a task and at least one valid tool")
    terms = sorted(terms_of(task))
    if not terms:
        raise ValueError("task has no usable words")
    return task, tools, terms


def apply(db, nt, task, tools, terms):
    term_rows, used_rows, fol_rows = [], [], []
    for w in terms:
        rows = db.fetch_term(w)
        cur = {f"{r['server']}__{r['name']}": r["c"] for r in rows}
        term_rows.append({"vertex": nid("term:" + w), "name": w,
                          "df": (rows[0]["df"] if rows else 0) + 1, "ntasks": nt})
        for t in tools:
            used_rows.append({"source_vertex": nid("term:" + w), "destination_vertex": nid(t),
                              "relationship_vertex": nid(f"{w}->{t}:USED_FOR"), "count": cur.get(t, 0) + 1})
    for a, b in {(x, y) for x, y in zip(tools, tools[1:]) if x != y}:
        cur = {f"{r['server']}__{r['name']}": r["c"] for r in db.fetch_follow(a)}
        fol_rows.append({"source_vertex": nid(a), "destination_vertex": nid(b),
                         "relationship_vertex": nid(f"{a}->{b}:FOLLOWS"), "count": cur.get(b, 0) + 1})
    db.batches("UNWIND $rows AS row MERGE (n {id: row.vertex}) "
               "SET n:Term, n.name = row.name, n.df = row.df, n.ntasks = row.ntasks", term_rows)
    db.batches("UNWIND $rows AS row MATCH (s:Term {id: row.source_vertex}), (d:Tool {id: row.destination_vertex}) "
               "MERGE (s)-[r:USED_FOR {id: row.relationship_vertex}]->(d) SET r.count = row.count", used_rows)
    if fol_rows:
        db.batches("UNWIND $rows AS row MATCH (s:Tool {id: row.source_vertex}), (d:Tool {id: row.destination_vertex}) "
                   "MERGE (s)-[r:FOLLOWS {id: row.relationship_vertex}]->(d) SET r.count = row.count", fol_rows)
    return len(used_rows), len(fol_rows)


def set_ntasks(db, nt):
    try:
        db.run("MATCH (w:Term) SET w.ntasks = $n", n=nt)
        return True
    except Exception:
        return False


def _state():
    if STATE["nt"] is None:
        try:
            s = json.loads(pathlib.Path(os.environ.get("STATE_FILE", "/data/state.json")).read_text())
        except Exception:
            s = {}
        STATE["nt"] = s.get("ntasks") or base_ntasks()
        STATE["replayed"] = s.get("replayed", 0)
    return STATE


def tool_ids():
    import traverse as tv
    return sorted(t["id"] for t in tv.catalog)


def status():
    s = _state()
    return {"persistence": journal.enabled(), "lessons_replayed": s["replayed"],
            "lessons_taught_since_start": s["taught"]}


def teach(task, tools, ip=""):
    import traverse as tv
    task, tools, terms = clean(task, tools, {t["id"] for t in tv.catalog})
    now = time.time()
    with LOCK:
        hits = [h for h in HITS.get(ip, []) if now - h < 3600]
        if ip and len(hits) >= 10:
            raise RuntimeError("limit reached: 10 lessons per hour per visitor")
        s = _state()
        if s["replayed"] + s["taught"] >= CAP:
            raise RuntimeError("this demo has reached its lesson limit")
        before = [t["id"] for t in tv.sel.select(task, 5)[0]]
        nt = s["nt"] + 1
        used, fol = apply(tv.db, nt, task, tools, terms)
        s["nt"], s["taught"] = nt, s["taught"] + 1
        HITS[ip] = hits + [now]
        set_ntasks(tv.db, nt)
        try:
            saved = journal.add(task, tools)
        except Exception:
            saved = False
        return {"task": task, "taught": tools, "terms": terms, "persisted": saved,
                "edges_written": {"USED_FOR": used, "FOLLOWS": fol},
                "before": before, "after": [t["id"] for t in tv.sel.select(task, 5)[0]]}
