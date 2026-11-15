#!/usr/bin/env python3
"""Build results/RESULTS.md from results/traces.jsonl. No numbers are typed by hand."""
import collections, json, pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent
rows = [json.loads(l) for l in (ROOT / "results" / "traces.jsonl").read_text().splitlines() if l.strip()]
by = collections.defaultdict(lambda: collections.defaultdict(list))
for r in rows:
    by[(r["method"], r["split"])][r["task_id"]].append(r)

out = ["# Results (generated from results/traces.jsonl)", "",
       "For each method and split: the last completed run of every task. Runs that died on an API error are excluded and counted in the last column.", "",
       "| method | split | tasks | passed | prompt tokens / task | LLM calls / task | API-error runs excluded |",
       "|---|---|---|---|---|---|---|"]
for (m, s), tasks in sorted(by.items()):
    ok, err = [], 0
    for tid, rs in tasks.items():
        good = [r for r in rs if not r.get("error")]
        err += len(rs) - len(good)
        if good:
            ok.append(good[-1])
    if not ok:
        out.append(f"| {m} | {s} | 0 | - | - | - | {err} |")
        continue
    n = len(ok)
    out.append(f"| {m} | {s} | {n} | {sum(bool(r['success']) for r in ok)}/{n} | "
               f"{round(sum(r['prompt_tokens'] for r in ok) / n):,} | {sum(r['llm_calls'] for r in ok) / n:.1f} | {err} |")

methods = sorted({m for (m, s) in by if s == "test"})
tasks = sorted({t for (m, s), d in by.items() if s == "test" for t in d})
out += ["", "## Per-task result on the held-out test tasks", "",
        "P = passed, F = failed, - = no clean run.", "",
        "| task | " + " | ".join(methods) + " |", "|---|" + "---|" * len(methods)]
for t in tasks:
    cells = []
    for m in methods:
        good = [r for r in by[(m, "test")].get(t, []) if not r.get("error")]
        cells.append("-" if not good else ("P" if good[-1]["success"] else "F"))
    out.append(f"| {t} | " + " | ".join(cells) + " |")

(ROOT / "results" / "RESULTS.md").write_text("\n".join(out) + "\n")
print("\n".join(out))
