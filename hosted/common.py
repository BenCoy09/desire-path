"""Points the repo's scripts at the container's HydraDB instead of ~/dp-data."""
import os, pathlib, sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT / "scripts"))

ADDR = os.environ.get("GRAPH_BOLT_ADDR", "127.0.0.1:28687")
TOKEN = pathlib.Path(os.environ["GRAPH_AUTH_TOKEN_FILE"]).read_text().strip()


def patch():
    from neo4j import GraphDatabase
    import learn_graph as lg

    def connect():
        d = GraphDatabase.driver(f"bolt://{ADDR}", auth=("neo4j", TOKEN))
        d.verify_connectivity()
        print("connected to HydraDB at", ADDR, flush=True)
        return d

    lg.connect = connect
