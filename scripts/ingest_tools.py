#!/usr/bin/env python3
"""Ingest saved MCP tool definitions into HydraDB.

Forms copied from HydraDB's cypher-compat.md:
  UNWIND $rows AS row MERGE (n {id: row.vertex}) SET n:Label, n.prop = ...
  UNWIND $rows AS row
    MATCH (s:A {id: row.x}), (d:B {id: row.y})
    MERGE (s)-[r:TYPE {id: row.rid}]->(d)
    SET r.prop = ...
"""
import json, pathlib, re, sys, zlib
from neo4j import GraphDatabase

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "data" / "tools"
TOKEN_PATH_FILE = pathlib.Path.home() / ".hydra_token_path"
LOG_FILE = pathlib.Path("/home/hpbenny/dp-data/graph-node.log")


def nid(text):
    return zlib.crc32(text.encode()) & 0x7FFFFFFF


def bolt_address():
    addrs = re.findall(r'"bolt_addr":"([^"]+)"', LOG_FILE.read_text())
    if not addrs:
        sys.exit("No bolt_addr found in graph-node.log. Is HydraDB running?")
    return addrs[-1]


def load_token():
    token_file = pathlib.Path(TOKEN_PATH_FILE.read_text().strip())
    return token_file.read_text().strip()


def main():
    addr = bolt_address()
    token = load_token()

    server_rows, tool_rows, edge_rows = [], [], []
    for path in sorted(TOOLS_DIR.glob("*.json")):
        server_name = path.stem
        sid = nid(server_name)
        server_rows.append({"vertex": sid, "name": server_name})
        for t in tools_of(path):
            tid = nid(f"{server_name}__{t['name']}")
            tool_rows.append({
                "vertex": tid,
                "name": t["name"],
                "server": server_name,
                "description": (t.get("description") or "")[:500],
                "chars": len(json.dumps(t)),
            })
            edge_rows.append({
                "source_vertex": sid,
                "destination_vertex": tid,
                "relationship_vertex": nid(f"{sid}->{tid}"),
                "kind": "hosts",
            })
    if not server_rows:
        sys.exit(f"No tool files found in {TOOLS_DIR}")

    ids = [r["vertex"] for r in server_rows + tool_rows]
    if len(ids) != len(set(ids)):
        sys.exit("id collision between nodes; tell Claude before continuing")
    eids = [r["relationship_vertex"] for r in edge_rows]
    if len(eids) != len(set(eids)):
        sys.exit("id collision between edges; tell Claude before continuing")

    driver = GraphDatabase.driver(f"bolt://{addr}", auth=("neo4j", token))
    driver.verify_connectivity()
    print("connected to", addr)

    with driver.session(database="default") as s:
        s.run(
            "UNWIND $rows AS row "
            "MERGE (n {id: row.vertex}) "
            "SET n:Server, n.name = row.name",
            rows=server_rows,
        ).consume()
        print(f"servers written: {len(server_rows)}")

        s.run(
            "UNWIND $rows AS row "
            "MERGE (n {id: row.vertex}) "
            "SET n:Tool, n.name = row.name, n.server = row.server, "
            "n.description = row.description, n.chars = row.chars",
            rows=tool_rows,
        ).consume()
        print(f"tools written: {len(tool_rows)}")

        s.run(
            "UNWIND $rows AS row "
            "MATCH (s:Server {id: row.source_vertex}), "
            "(d:Tool {id: row.destination_vertex}) "
            "MERGE (s)-[r:HOSTS {id: row.relationship_vertex}]->(d) "
            "SET r.kind = row.kind",
            rows=edge_rows,
        ).consume()
        print(f"HOSTS edges written: {len(edge_rows)}")

        for label, q in (
            ("Tool nodes", "MATCH (t:Tool) RETURN count(t) AS n"),
            ("HOSTS edges", "MATCH (s:Server)-[e:HOSTS]->(t:Tool) RETURN count(*) AS n"),
        ):
            try:
                print(f"graph check, {label}:", s.run(q).single()["n"])
            except Exception as e:
                print(f"graph check, {label} FAILED:", type(e).__name__, str(e)[:200])

    driver.close()


def tools_of(path):
    return json.loads(path.read_text())


if __name__ == "__main__":
    main()
