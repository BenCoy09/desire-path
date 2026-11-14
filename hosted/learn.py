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


# ---- per-user private layer: user-scoped Term nodes pointing at the shared Tool nodes
PQ = ("MATCH (w:Term {id: %d})-[r:USED_FOR]->(t:Tool) RETURN w.df AS df, "
      "t.server AS server, t.name AS name, r.count AS c")


def apply_user(db, uid, task, tools, terms):
    tr, ur = [], []
    for w in terms:
        vid = nid(f"u{uid}:term:{w}")
        rows = db.run(PQ % vid)
        cur = {f"{r['server']}__{r['name']}": r["c"] for r in rows}
        tr.append({"vertex": vid, "name": w, "df": (rows[0]["df"] if rows else 0) + 1, "ntasks": 0})
        for t in tools:
            ur.append({"source_vertex": vid, "destination_vertex": nid(t),
                       "relationship_vertex": nid(f"u{uid}:{w}->{t}"), "count": cur.get(t, 0) + 1})
    db.batches("UNWIND $rows AS row MERGE (n {id: row.vertex}) "
               "SET n:Term, n.name = row.name, n.df = row.df, n.ntasks = row.ntasks", tr)
    db.batches("UNWIND $rows AS row MATCH (s:Term {id: row.source_vertex}), (d:Tool {id: row.destination_vertex}) "
               "MERGE (s)-[r:USED_FOR {id: row.relationship_vertex}]->(d) SET r.count = row.count", ur)


def user_select(uid, task, k=5):
    import traverse as tv
    from collections import Counter
    n_u = journal.count(uid)

    def ft(w):
        base = tv.db.fetch_term(w)
        mine = tv.db.run(PQ % nid(f"u{uid}:term:{w}"))
        if not mine:
            return base
        c = Counter()
        for r in base + mine:
            c[(r["server"], r["name"])] += r["c"]
        df = (base[0]["df"] if base else 0) + mine[0]["df"]
        return [{"server": s, "name": n, "c": v, "df": df, "ntasks": _state()["nt"] + n_u} for (s, n), v in c.items()]

    sel = lg.Selector(ft, tv.sel.fetch_follow, tv.catalog, tv.sel.bm25)
    t0 = time.perf_counter()
    tools, info = sel.select(task, k)
    return tools, info, round((time.perf_counter() - t0) * 1000, 1)


def teach_user(uid, task, tools):
    import traverse as tv
    task, tools, terms = clean(task, tools, {t["id"] for t in tv.catalog})
    with LOCK:
        if journal.count(uid) >= 200:
            raise RuntimeError("workspace lesson limit reached (200)")
        before = [t["id"] for t in user_select(uid, task)[0]]
        journal.add(task, tools, uid)
        apply_user(tv.db, uid, task, tools, terms)
        return {"before": before, "after": [t["id"] for t in user_select(uid, task)[0]], "persisted": True}
