# Desire Path

> Agents shouldn't load every tool. They should follow the trail earlier tasks already wore into the graph.

**Demo video:** https://youtu.be/PtK8uJR-uN4 · **Live app:** https://desire-path.onrender.com (free host: the first visit can take about a minute to wake) · **Try it without signing up:** open `/account.html` and click *Try the demo* · **API:** `/docs.html`

Built for the HydraDB hackathon (Nov 14–16, 2026), **Track 2: the agent context layer**. HydraDB is the graph database.

---

## The result

Real Gemini agents (`gemini-3.1-flash-lite`) used real MCP tools on 10 held-out tasks. Success is checked by code (answer text, files on disk, memory contents), not by an LLM judge.

| Tools given to the agent | Passed | Prompt tokens per task | LLM calls per task |
| --- | --- | --- | --- |
| All 42 tools, every call (preload) | 10/10 | 29,352 | 4.3 |
| Keyword search (BM25), top 5 | 4/10 | 10,835 | 5.9 |
| Keyword search (BM25), top 3 | 2/10 | 5,622 | 6.3 |
| **Desire Path graph, 5 tools** (run `graph_k5`) | **10/10** | **3,241** | **3.1** |

The graph matched the pass rate of loading everything with about **89% fewer prompt tokens** (3,241 vs 29,352) and about 28% fewer LLM calls. Keyword search with a similar budget failed most tasks: it picked the wrong tools, and the agent looped on them.

These rows are generated from `results/traces.jsonl` by `python scripts/make_results.py` (output: `results/RESULTS.md`, with a per-task pass/fail matrix). Runs that died on API errors are excluded and counted there.

### Scale check (partial)
We padded the catalog with synthetic tools (`results/synth_catalog_100.json`, `_300`, `_1000`) to test routing among more distractors. With 100 extra synthetic tools offered alongside the 42 real ones, the graph again passed **10/10** at 3,239 prompt tokens per task (run `graph_5_N100`). The 300- and 1,000-tool runs **did not finish**: they hit API quota errors (0 clean runs at 300, 1 at 1,000), so we report no result for them. Preload with those extra tools also never completed, so we make no comparison against it.

### Retrieval check (no model calls)
On the same 10 held-out tasks: how many of the tools the agent really needed did the router return? This runs against the live graph (`GET /eval`) and can drift slightly because visitors can teach the shared demo.

| Tools returned (k) | Method | Recall | Precision | All needed found |
| --- | --- | --- | --- | --- |
| 3 | Graph | 0.97 | 0.55 | 0.90 |
| 3 | Graph without sequence edges | 0.97 | 0.55 | 0.90 |
| 3 | Keyword (BM25) | 0.27 | 0.17 | 0.10 |
| 5 | Graph | 0.97 | 0.36 | 0.90 |
| 5 | Graph without sequence edges | 0.97 | 0.38 | 0.90 |
| 5 | Keyword (BM25) | 0.30 | 0.12 | 0.20 |

With nothing learned, the router behaves like keyword search (recall 0.27 at k=3, first rows of `results/learning_curve.json`). After learning from the 20 learning tasks it reads 0.97.

## Why a desire path

A desire path is the dirt track people wear across a lawn along the shortcut they actually want. Agent tooling is still paved in advance: every tool, every prompt. We do the opposite. Let the agent walk, record which tools each successful task needed, and make those trails the map.

## How it works

~~~text
 task: "read the config file and write a summary"
          |
          v   words (stop-words removed)
   [read] [config] [file] [write] [summary]        <- Term nodes
          |  USED_FOR {count}   weighted, idf-scored
          v
   read_text_file   write_file   list_directory    <- Tool nodes
          |  FOLLOWS {count}    one hop, only strong follow-ups
          v
   top-k tools go into the prompt. Nothing else does.
~~~

~~~mermaid
flowchart LR
  A[Successful agent runs] -->|backward slice: keep only calls that mattered| B[Learn]
  B -->|Term USED_FOR Tool, Tool FOLLOWS Tool| C[(HydraDB v0.4.0)]
  D[New task] -->|graph walk per request| C
  C --> E[Top-k tools]
  F[Teach it / lessons] -->|journal in Postgres, replayed on restart| C
~~~

**Schema** (all in HydraDB, Cypher over Bolt):
- `(Server)-[:HOSTS]->(Tool)`: the catalog, from four MCP servers (everything, filesystem, memory, sequential-thinking).
- `(Term)-[:USED_FOR {count}]->(Tool)`: task words to the tools that were needed.
- `(Tool)-[:FOLLOWS {count}]->(Tool)`: tool B directly after tool A in the kept calls.

**Learning** (`scripts/learn_graph.py`): from successful traces on the learning split only. A backward slice keeps a call only if it changed state or its output was later used, so detours the agent explored and abandoned are not learned. Counts become edge weights.

**Routing** (`scripts/traverse.py`, `Selector` in `scripts/learn_graph.py`): fetch each task word's edges, score tools by idf-weighted share of counts, take the top picks, follow strong `FOLLOWS` edges one hop, fill to k. If no word is known it says `no_confident_match`, and the caller should load the full catalog.

## Does it need a graph? The honest answer

- **What does the work today:** the learned word-to-tool links. They lift recall from about 0.3 (keyword search) to 0.97.
- **What did not help:** the tool-to-tool `FOLLOWS` edges. Removing them leaves recall unchanged at both k=3 and k=5 (precision 0.55 vs 0.55, and 0.38 vs 0.36).
- **What we have not shown:** that the graph beats a plain dictionary of learned word-to-tool counts. At 42 tools a dictionary would likely return the same tools. We have not built that comparison, so we do not claim it.
- **Why it still lives in HydraDB:** every request issues real Cypher to the graph (cache off for benchmarks); lessons are written into the same graph and replayed from a Postgres journal after restarts; private workspaces are overlays of user-scoped `Term` nodes pointing into the shared `Tool` nodes.
- **Where a graph should become necessary:** multi-hop structure such as prerequisites (a tool that must run before another and is not named in the task). We started that experiment (`scripts/predecessor.py`, raw output in `results/predecessor.txt`). The agent-run version (`scripts/run_prereq.py`) did not complete because of API quota, so it makes no claim here.

## Evidence you can check

| Claim | Where to check |
| --- | --- |
| End-to-end results table | `python scripts/make_results.py`, then `results/RESULTS.md` (generated from `results/traces.jsonl`) |
| Learning split and test split do not overlap | `learn_graph.py` asserts there is no task overlap ("split leak") before learning |
| Recall, precision and the ablation | App → **Evaluate** tab, or `GET /eval` |
| It improves with learning | `results/learning_curve.json` (plotted on the landing page) |
| Behavior under concurrent load | App → **Benchmark** tab; raw outputs in `results/load_ttl0.txt` (cache off) and `results/load_ttl60.txt` |
| Lessons survive restarts | Teach a lesson, restart the Render service, route again |
| Private workspaces are private | Sign up two accounts; lessons in one do not change the other |

## What we did not show

- **Small test:** 10 held-out tasks, one clean run each, one model, free-tier API. One task moves a rate by 10 points.
- **Same task families:** the test tasks are new instances of the same workflow families the graph learned from. We have not shown it transfers to new kinds of work.
- **Limited baselines:** loading everything and one-shot keyword search only. No agent that can search again, and no embedding baseline.
- **Scale:** only the run with 100 extra synthetic tools finished (see above).
- **Precision is low:** the router favors recall. At k=5 it returns extra tools, and the token cost is still about a tenth of loading everything.
- **Sequence edges** did not help on this catalog.
- **SelfGraph:** we tried it and dropped it. Its writes failed because our local-file object store does not implement `PutMode::Update`, so the history page is our own Postgres log of every lesson.
- **Fixed catalog:** four MCP servers. Bring-your-own catalog is the first roadmap item.
- **Free-tier host:** the demo sleeps when idle and HydraDB's disk resets on restart; lessons are replayed from Postgres.
- **Shared demo is open:** lessons taught on the public app change routing for everyone (rate-limited to 10 per hour per visitor). Private workspaces do not.
- **No paying customers yet.**

## Who would pay

Teams running agents against many MCP servers, where tool definitions are paid for on every call. In our runs, loading 42 tools cost 29,352 prompt tokens per task and the graph cut that to 3,241. Over 1,000 tasks that is about 26.1 million fewer input tokens, so the saving is **26.1 × your price per 1M input tokens, in dollars, per 1,000 tasks**.

Proposed plans (not charging yet): **Open source** (free, self-host) · **Team** ($49/month, proposed: hosted graph, usage dashboard, shared learning across agents) · **Enterprise** (private deployment, audit trail, custom catalogs). Early access: open an issue at https://github.com/BenCoy09/desire-path/issues. Roadmap: bring-your-own tool catalog, per-user API keys, password reset, billing, and a search-again baseline.

## Hackathon fit

| Criterion | Where to look |
| --- | --- |
| Engineering: real graph traversal | `Selector` in `scripts/learn_graph.py`; every `/select` issues Cypher to HydraDB (`scripts/traverse.py`) |
| Engineering: does it need the graph? | The section above, which states what did not help |
| Engineering: holds up under load | Benchmark tab; `results/load_ttl0.txt` |
| Go-to-market: who and why | The section above: buyer, measured saving per task, proposed plans, and the limits |

## For agent builders

~~~bash
curl "https://desire-path.onrender.com/select?k=5&task=read+the+config+file+and+summarize+it"
curl -X POST https://desire-path.onrender.com/learn -H "Content-Type: application/json" \
  -d '{"task":"read the config file and summarize it","tools":["filesystem__read_text_file","filesystem__write_file"]}'
~~~

Estimate what loading your own tools costs at `/connect.html` (runs in your browser; export your server's tools with `python scripts/export_mcp_tools.py my_tools.json -- <your MCP server command>`). Hosted per-developer catalogs are not available yet.

The loop: route, load only those tool definitions, run, then teach the tools the run actually used. Full API: `/docs.html`.

## Run it

**Docker:**

~~~bash
docker build -t desire-path .
docker run -p 8080:8080 desire-path        # http://localhost:8080
~~~

The image starts HydraDB (`graph-node` + `graph-indexer`, v0.4.0), builds the graph from `data/tools/` and `results/traces.jsonl`, then serves the site and API. Optional environment: `DATABASE_URL` (Postgres: accounts and saved lessons), `MAIL_RELAY_URL`, `MAIL_RELAY_SECRET`, `PUBLIC_URL`.

**Scripts against a local HydraDB** (the scripts expect the author's `~/dp-data` paths; edit them in `scripts/ingest_tools.py` and `connect()` in `scripts/learn_graph.py`):

~~~bash
pip install -r requirements.txt
python scripts/ingest_tools.py      # servers and tools into HydraDB
python scripts/learn_graph.py       # learn Term and FOLLOWS edges, print the offline evaluation
python scripts/traverse.py          # routing service on :8099
python scripts/load_test.py         # concurrent load test
python scripts/make_results.py      # regenerate results/RESULTS.md from the real traces
~~~

## Repo map

~~~text
scripts/   ingest_tools.py  learn_graph.py  traverse.py  run_agent.py  run_graph.py
           make_results.py  load_test.py  baseline_bm25.py  ...
           experiment scripts: scale_test.py, predecessor.py, family_holdout.py, hybrid.py
hosted/    server.py  learn.py  evalrun.py  accounts.py  journal.py  restore_graph.py
site/      landing, app, docs, history, account pages
data/tools tool definitions from four MCP servers
results/   traces.jsonl, RESULTS.md, learning_curve.json, load tests, raw experiment outputs
Dockerfile start.sh                           one container: HydraDB + service
~~~

## Credits

Built on the open-source [HydraDB](https://github.com/hydra-db/hydradb) engine (v0.4.0). Tool definitions come from public MCP servers. Hosted on Render with Neon Postgres for accounts and the lesson journal.

License: MIT.

## Use it from Claude (MCP)

`scripts/dp_mcp.py` is a small MCP server (stdio, Python standard library only). It lets an MCP client ask Desire Path which tools a task needs, and optionally teach it what a run used. It calls the public API, so by default it talks to the shared demo.

| Tool | What it does |
|---|---|
| `route_tools(task, k)` | Returns the tool ids to load for the task (a graph lookup in HydraDB) |
| `list_catalog()` | Lists the tool ids Desire Path knows |
| `teach_tools(task, tools)` | Teaches it which tools a finished task used. Off unless `DESIRE_PATH_ALLOW_TEACH=1`, because the demo graph is shared |

Claude Code:

```bash
claude mcp add desire-path -- python3 /path/to/desire-path/scripts/dp_mcp.py
```

Claude Desktop (`claude_desktop_config.json`):

```json
{"mcpServers": {"desire-path": {"command": "python3", "args": ["/path/to/desire-path/scripts/dp_mcp.py"]}}}
```

Set `DESIRE_PATH_URL` to use your own deployment instead of the demo.

Status: tested from the command line against a stand-in API. Not yet verified inside any MCP client. A client that connects this server still loads its other servers' tool definitions as usual; the saving comes when an agent calls `route_tools` first and loads only the tools it returns. Per-workspace API keys are not built yet.
