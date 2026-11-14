"""Startup: rebuild the tool graph, then the learned edges from saved traces."""
import sys
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
print("restore complete", flush=True)
