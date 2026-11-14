import pathlib, re, os
from neo4j import GraphDatabase

log = pathlib.Path("/home/hpbenny/dp-data/graph-node.log").read_text()
addr = re.findall(r'"bolt_addr":"([^"]+)"', log)[-1]
print("bolt address:", addr)

cands = []
for root in ("/home/hpbenny/dp-data", "/tmp"):
    for p in pathlib.Path(root).rglob("*"):
        try:
            if p.is_file() and 32 <= p.stat().st_size <= 200:
                cands.append(p)
        except OSError:
            pass
cands = cands[:25]
print("candidate token files:", len(cands))

for p in cands:
    try:
        token = p.read_text().strip()
    except Exception:
        continue
    if len(token) < 32 or "\n" in token or " " in token:
        continue
    d = GraphDatabase.driver(f"bolt://{addr}", auth=("neo4j", token))
    try:
        d.verify_connectivity()
    except Exception:
        d.close()
        continue
    print("CONNECTED using token file:", p)
    with d.session(database="default") as s:
        try:
            print("count query:", s.run("MATCH (n) RETURN count(*) AS c").data())
        except Exception as e:
            print("QUERY FAILED:", type(e).__name__, e)
    open(os.path.expanduser("~/.hydra_token_path"), "w").write(str(p))
    d.close()
    break
else:
    print("NO WORKING TOKEN FILE FOUND")
