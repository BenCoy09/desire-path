# desire-path

> Agents spend most of their prompt on tools they never use. **desire-path** learns which few tools a task actually needs, from real agent runs, and keeps that knowledge as a graph in HydraDB.

HydraDB Hackathon · Track 2: the agent context layer

## Result at a glance

On 10 held-out tasks, using real Gemini runs, the graph selector passed **10/10** with **3,239 prompt tokens per task**. That is about **9x fewer** than loading every tool (29,352). Keyword search with a similar budget passed only 2 to 4 of 10.

| Method | Passed | Prompt tokens / task | LLM calls / task |
|---|---|---|---|
| Preload all 42 tools | 10/10 | 29,352 | 4.3 |
| BM25 keyword search, top 5 | 4/10 | 10,835 | 5.9 |
| BM25 keyword search, top 3 | 2/10 | 5,622 | 6.3 |
| **desire-path graph, 5 tools** | **10/10** | **3,239** | **3.1** |

Model: `gemini-3.1-flash-lite`. Pass or fail is checked by code (answer text, files on disk, memory contents), never by an LLM judge. Every run is saved in `results/traces.jsonl`.

## The problem

Loading 42 tool definitions into every LLM call cost about 29k prompt tokens per task in our runs. Picking tools by keyword is cheap, but it often misses the tool the task needs: top-3 BM25 failed 8 of 10 tasks, and the agent looped on the wrong tools.

## How it works

    task text
       |  split into terms
       v
    learned links: term -> tool           (graph stored in HydraDB)
       |  score tools; rarer terms count more
       v
    top tools, plus "follow" edges        (tools that were used together)
       |
       v
    k tools handed to the agent  -->  the agent runs with only those tools

    No known term in the task?  -> "no confident match". It does not guess.

- **Nodes:** `Server` and `Tool`, ingested from real MCP servers (filesystem, memory, everything, sequential-thinking: 42 tools).
- **Edges:** `HOSTS` (server to tool) plus links learned from agent traces on the learning tasks (`scripts/learn_graph.py`).
- **Selection:** weighted term-to-tool scores, then up to k tools including tools that followed the top picks in earlier runs.
- **Static page:** `site/` runs the same selector in the browser from an exported snapshot and re-checks the test tasks against the Python selector. It is a snapshot, not a live database query.

## Engineering notes (HydraDB, local-file mode)

Things we hit and had to design around:
- Updating existing records failed with `PutMode::Update not yet implemented by LocalFileSystem` (seen in the graph-node log).
- `MATCH (n)` with no label, id or property is rejected.
- Node ids are numeric (`crc32(text) & 0x7FFFFFFF` in `scripts/ingest_tools.py`).
- `MERGE ... SET` and edge writes failed in our probe (`scripts/probe_writes.py`).

## Honest limits

- **Small sample:** 10 test tasks, one run each.
- **Same families:** test tasks are new instances of workflows the graph learned from. This does not show transfer to new kinds of work.
- **Baselines:** preload and one-shot BM25 only. No search-again baseline and no embedding baseline yet.
- **Thin graph:** mostly term-to-tool links plus a few follow edges. It is closer to a learned lookup table than a deep traversal.
- **Quota errors:** the 300- and 1,000-tool runs and `preload_all_N100` died on API errors and are not results. `graph_k5` (10 of 12 completed, 2 errors) is an earlier run.
- **Free tier:** a single model on the free API tier.

## Reproduce

1. Build HydraDB from `hydra-db/hydradb`. It needs LAGraph (`scripts/install_lagraph.sh` in that repo), then `just mcp-local ~/dp-data`.
2. `python3 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt`
3. Put `GEMINI_API_KEY` and `GEMINI_MODEL` in `~/.desire-path.env` (never commit it).
4. `python scripts/ingest_tools.py` loads the tool graph into HydraDB.
5. `python scripts/run_agent.py --method preload --split test` runs a baseline (also `--method bm25 --k 5`).
6. See the header of `scripts/run_graph.py` for the graph runs.
7. `bash scripts/status.sh` prints the results table from `results/traces.jsonl`.

## Repo map

- `scripts/run_agent.py`: agent runner and the 30 code-checked tasks
- `scripts/ingest_tools.py`: loads MCP tool definitions into HydraDB
- `scripts/learn_graph.py`, `scripts/run_graph.py`: the learned selector
- `scripts/export_snapshot.py`: exports the graph to `site/graph.json`
- `site/`: static demo page
- `results/traces.jsonl`: every real agent run

Not to be confused with `scbrown/desire-path`, which aggregates failed tool calls. This project selects tools for an agent.
