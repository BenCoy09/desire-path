"""Startup: base graph, learned edges from traces, then replay saved lessons."""
import json, os, pathlib, sys
import common

common.patch()
import ingest_tools as it
it.bolt_address = lambda: common.ADDR
it.load_token = lambda: common.TOKEN
it.main()

import learn_graph as lg
sys.argv = ["learn_graph.py"]
try:
    lg.main()
except SystemExit as e:
    if e.code not in (None, 0):
        raise

import learn, journal
nt, replayed = learn.base_ntasks(), 0
try:
    if journal.enabled():
        journal.init()
        ids = {t["id"] for t in lg.load_catalog()}
        db = lg.Hydra()
        for task, tools in journal.all_lessons():
            try:
                task, tools, terms = learn.clean(task, tools, ids)
            except ValueError:
                continue
            learn.apply(db, nt + 1, task, tools, terms)
            nt += 1
            replayed += 1
        if replayed:
            learn.set_ntasks(db, nt)
    print(f"journal: replayed {replayed} lessons", flush=True)
except Exception as e:
    print("journal unavailable:", type(e).__name__, str(e)[:200], flush=True)
pathlib.Path(os.environ.get("STATE_FILE", "/data/state.json")).write_text(json.dumps({"ntasks": nt, "replayed": replayed}))
print("restore complete", flush=True)
