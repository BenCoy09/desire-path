#!/usr/bin/env python3
"""Real Gemini runs of the prerequisite tasks with ALL tools loaded. Results are appended to traces.jsonl."""
import json, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_agent as ra
from prereq_tasks import PREREQ

catalog = ra.load_catalog()
pool = ra.Pool()
out = ra.RESULTS / "traces.jsonl"
for t in PREREQ:
    tr = ra.run_task(t, catalog, pool, "preload_prereq")
    with out.open("a") as f:
        f.write(json.dumps(tr, ensure_ascii=False) + "\n")
    used = ",".join(c["tool"].split("__", 1)[-1] for c in tr["calls"])
    print(t["id"], "PASS" if tr["success"] else "FAIL", "llm=%d" % tr["llm_calls"], "tools=[%s]" % used,
          "" if tr["success"] else (tr["error"] or tr["check_detail"]), flush=True)
    if "HTTP 429" in tr["error"]:
        print("quota hit: stopping"); break
pool.reset()
