#!/usr/bin/env python3
"""Find which write shape HydraDB rejects, and show the server's own error lines."""
import pathlib, random, subprocess, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from learn_graph import connect

d = connect()
base = random.randint(10**8, 10**9)
UP = ("UNWIND $rows AS row MERGE (n {id: row.vertex}) "
      "SET n:DpProbe, n.name = row.name, n.df = row.df, n.ntasks = row.ntasks")
UP_STR = "UNWIND $rows AS row MERGE (n {id: row.vertex}) SET n:DpProbe, n.name = row.name"


def row(i, df=1):
    return {"vertex": base + i, "name": f"p{i}", "df": df, "ntasks": 20}


def t(name, cy, **p):
    try:
        with d.session(database="default") as s:
            s.run(cy, **p).consume()
        print("PASS", name)
    except Exception as e:
        print("FAIL", name, "|", str(e).replace("\n", " ").split("message:", 1)[-1][:170])


t("1 one new node (strings + ints)", UP, rows=[row(1)])
t("2 same node again (update existing)", UP, rows=[row(1, df=2)])
t("3 one new node, string props only", UP_STR, rows=[row(2)])
t("4 batch of 20 new nodes", UP, rows=[row(i) for i in range(10, 30)])
t("5 batch of 150 new nodes", UP, rows=[row(i) for i in range(100, 250)])
t("6 plain CREATE", "CREATE (n:DpProbe {id: %d, name: 'x'})" % (base + 900))
for name in ("graph-node.log", "graph-indexer.log"):
    out = subprocess.run(
        f"grep -i -E 'error|panic|not implemented|unsupported|fail' /home/hpbenny/dp-data/{name} | tail -5 | cut -c1-380",
        shell=True, capture_output=True, text=True).stdout
    print(f"--- {name} (last error-like lines)")
    print(out or "(none)")
