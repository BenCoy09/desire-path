#!/usr/bin/env python3
"""Live run: the agent gets ONLY the tools the HydraDB graph selects for each task.
Usage: python scripts/run_graph.py [--k 5] [--split test] [--tasks T01,T02] [--rerun]
Traces go to results/traces.jsonl with method graph_k<K>, like the other methods."""
import argparse, json, pathlib, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_agent as ra
import learn_graph as lg


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--split", default="test")
    ap.add_argument("--tasks", default="")
    ap.add_argument("--rerun", action="store_true")
    a = ap.parse_args()
    if not ra.KEY or not ra.MODEL:
        sys.exit("GEMINI_API_KEY / GEMINI_MODEL missing in ~/.desire-path.env")
    catalog = ra.load_catalog()
    bm = ra.Bm25(catalog)
    db = lg.Hydra()
    sel = lg.Selector(db.fetch_term, db.fetch_follow, catalog, bm)
    method = f"graph_k{a.k}"
    out_file = ra.RESULTS / "traces.jsonl"
    done = set()
    if out_file.exists() and not a.rerun:
        for line in out_file.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not r.get("error"):
                done.add((r["task_id"], r["method"]))
    want = [x for x in a.tasks.split(",") if x]
    todo = [t for t in ra.TASKS if (not want or t["id"] in want)
            and (not a.split or t["split"] == a.split) and (t["id"], method) not in done]
    print(f"model {ra.MODEL} | method {method} | {len(todo)} tasks to run")
    pool = ra.Pool()
    results = []
    for t in todo:
        tools, info = sel.select(t["prompt"], a.k)
        tr = ra.run_task(t, tools, pool, method)
        tr["graph_info"] = info
        with out_file.open("a") as f:
            f.write(json.dumps(tr, ensure_ascii=False) + "\n")
        results.append(tr)
        offered = ",".join(x["name"] for x in tools)
        used = ",".join(c["tool"].split("__", 1)[-1] for c in tr["calls"])
        tail = "" if tr["success"] else f" | {tr['error'] or tr['check_detail']}"
        fb = " FALLBACK" if info["fallback"] else ""
        print(f"{t['id']} {'PASS' if tr['success'] else 'FAIL'}{fb} llm={tr['llm_calls']} "
              f"prompt_tok={tr['prompt_tokens']} offered=[{offered}] used=[{used}]{tail}")
        if "HTTP 429" in tr["error"]:
            print("quota hit: stopping. Rerun later; finished tasks are skipped.")
            break
    pool.reset()
    if results:
        n = len(results)
        print(f"--- {method}: {sum(r['success'] for r in results)}/{n} passed | "
              f"mean prompt tokens {sum(r['prompt_tokens'] for r in results) / n:.0f} | "
              f"mean LLM calls {sum(r['llm_calls'] for r in results) / n:.1f}")


if __name__ == "__main__":
    main()
