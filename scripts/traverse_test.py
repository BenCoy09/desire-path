import pathlib, re, sys, zlib
from neo4j import GraphDatabase

def nid(text):
    return zlib.crc32(text.encode()) & 0x7FFFFFFF

server = sys.argv[1] if len(sys.argv) > 1 else "memory"
log = pathlib.Path("/home/hpbenny/dp-data/graph-node.log").read_text()
addr = re.findall(r'"bolt_addr":"([^"]+)"', log)[-1]
tok = pathlib.Path(pathlib.Path.home().joinpath(".hydra_token_path").read_text().strip()).read_text().strip()

d = GraphDatabase.driver(f"bolt://{addr}", auth=("neo4j", tok))
with d.session(database="default") as s:
    q = f"MATCH (s:Server {{id: {nid(server)}}})-[:HOSTS]->(t:Tool) RETURN t.name AS name"
    try:
        rows = s.run(q).data()
        print(f"server '{server}' hosts {len(rows)} tools:")
        for r in rows:
            print("  ", r["name"])
    except Exception as e:
        print("QUERY FAILED:", type(e).__name__, str(e)[:300])
d.close()
