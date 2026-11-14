import json, pathlib, collections
f = pathlib.Path(__file__).resolve().parent.parent / "results" / "traces.jsonl"
rows = collections.defaultdict(dict)
for line in f.read_text().splitlines():
    try: r = json.loads(line)
    except ValueError: continue
    if not r.get("error"): rows[r["method"]][r["task_id"]] = r  # latest per task
print(f"{'method':<14}{'pass':>8}{'mean tok':>10}{'mean llm':>10}")
for m, d in sorted(rows.items()):
    n = len(d)
    print(f"{m:<14}{sum(x['success'] for x in d.values()):>5}/{n:<2}"
          f"{sum(x['prompt_tokens'] for x in d.values())/n:>10.0f}"
          f"{sum(x['llm_calls'] for x in d.values())/n:>10.1f}")
