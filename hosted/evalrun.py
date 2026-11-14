"""Live held-out evaluation: graph vs graph-without-sequence-edges vs BM25."""
import json, time
import learn_graph as lg

TESTS = []
CACHE = [0, None]


def measured():
    traces = [json.loads(l) for l in lg.TRACES.read_text().splitlines() if l.strip()]
    out = {}
    for label, method in (("preload", "preload"), ("bm25_top5", "bm25_top5"), ("bm25_top3", "bm25_top3"), ("graph_5", "graph_5_N100")):
        last = {}
        for r in traces:
            if r.get("method") == method and r.get("split") == "test" and not r.get("error"):
                last[r["task_id"]] = r
        if last:
            rs = list(last.values())
            n = len(rs)
            out[label] = {"passed": sum(bool(r["success"]) for r in rs), "n": n,
                          "prompt_tokens": round(sum(r["prompt_tokens"] for r in rs) / n),
                          "llm_calls": round(sum(r["llm_calls"] for r in rs) / n, 1)}
    return out


def run(ks=(3, 5)):
    import traverse as tv
    if CACHE[1] and time.time() - CACHE[0] < 30:
        return CACHE[1]
    if not TESTS:
        traces = [json.loads(l) for l in lg.TRACES.read_text().splitlines() if l.strip()]
        for tr in lg.last_valid(traces, "test"):
            need = {c["tool"] for c in lg.used_calls(tr)}
            if need:
                TESTS.append((tr["prompt"], need))
    if not TESTS:
        raise ValueError("no held-out tasks found")
    chars = {t["id"]: t["chars"] for t in tv.catalog}
    flat = lg.Selector(tv.sel.fetch_term, lambda tid: [], tv.catalog, tv.sel.bm25)
    methods = [("graph", lambda p, k: tv.sel.select(p, k)[0]),
               ("graph without sequence edges", lambda p, k: flat.select(p, k)[0]),
               ("keyword baseline (BM25)", lambda p, k: tv.sel.bm25.top(p, k))]
    rows = []
    for k in ks:
        for name, fn in methods:
            rec = prec = full = tok = 0.0
            for prompt, need in TESTS:
                ids = {t["id"] for t in fn(prompt, k)}
                hit = len(need & ids)
                rec += hit / len(need)
                prec += hit / max(1, len(ids))
                full += need <= ids
                tok += sum(chars.get(i, 0) for i in ids) // 4
            n = len(TESTS)
            rows.append({"method": name, "k": k, "recall": round(rec / n, 2), "precision": round(prec / n, 2),
                         "all_found": round(full / n, 2), "tokens": round(tok / n)})
    out = {"tasks": len(TESTS), "preload_tokens": sum(chars.values()) // 4, "rows": rows, "measured": measured()}
    CACHE[0], CACHE[1] = time.time(), out
    return out
