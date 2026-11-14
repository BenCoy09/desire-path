#!/usr/bin/env python3
"""BM25 tool-selection baseline vs preloading all tools.
Labels are hand-written (by Claude, to be reviewed) and use only tool names
seen in data/tools. Token figures are approximate (chars / 4)."""
import json, math, pathlib, re
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent

tools = []
for p in sorted((ROOT / "data" / "tools").glob("*.json")):
    for t in json.loads(p.read_text()):
        tools.append({
            "id": f"{p.stem}__{t['name']}",
            "text": (t["name"] + " ") * 2 + (t.get("description") or ""),
            "chars": len(json.dumps(t)),
        })

def tok(s):
    return re.findall(r"[a-z0-9]+", s.lower())

docs = [tok(t["text"]) for t in tools]
N = len(docs)
avgdl = sum(len(d) for d in docs) / N
df = Counter()
for d in docs:
    df.update(set(d))

def bm25(query, i, k1=1.5, b=0.75):
    tf = Counter(docs[i])
    score = 0.0
    for q in tok(query):
        if q not in tf:
            continue
        idf = math.log(1 + (N - df[q] + 0.5) / (df[q] + 0.5))
        score += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * len(docs[i]) / avgdl))
    return score

F, M = "filesystem__", "memory__"
TASKS = [
    ("Read the contents of notes.txt", {F + "read_text_file"}),
    ("Show me all files in the project folder", {F + "list_directory"}),
    ("Create a new folder called reports and save summary.txt inside it", {F + "create_directory", F + "write_file"}),
    ("Find every file named config in the workspace", {F + "search_files"}),
    ("Rename draft.txt to final.txt", {F + "move_file"}),
    ("Change one line in settings.json", {F + "edit_file"}),
    ("Remember that Alice works at Acme", {M + "create_entities", M + "create_relations"}),
    ("What do I know about Alice?", {M + "search_nodes"}),
    ("Dump the whole knowledge graph", {M + "read_graph"}),
    ("Read todo.txt and store its tasks in memory", {F + "read_text_file", M + "create_entities"}),
    ("Show the folder structure as a tree", {F + "directory_tree"}),
    ("Delete the memory entity for Bob", {M + "delete_entities"}),
    ("How big is log.txt and when was it modified", {F + "get_file_info"}),
    ("Copy template.md to a new file", {F + "copy_file"}),
    ("Read a.txt and b.txt together", {F + "read_multiple_files"}),
]

known = {t["id"] for t in tools}
for prompt, req in TASKS:
    missing = req - known
    if missing:
        raise SystemExit(f"label uses unknown tool id: {missing}")

def run(k):
    rec, allhit, toks = [], 0, []
    for prompt, req in TASKS:
        ranked = sorted(range(N), key=lambda i: -bm25(prompt, i))[:k]
        got = {tools[i]["id"] for i in ranked}
        rec.append(len(req & got) / len(req))
        allhit += req <= got
        toks.append(sum(tools[i]["chars"] for i in ranked) // 4)
        if not req <= got:
            print(f"  k={k} MISS: {prompt!r} missing {sorted(req - got)}")
    return sum(rec) / len(rec), allhit / len(TASKS), sum(toks) / len(toks)

preload = sum(t["chars"] for t in tools) // 4
print(f"tools: {N} | preload-all: recall 1.00, ~{preload} tokens/call (approx)")
for k in (3, 5):
    r, a, tk = run(k)
    print(f"BM25 top-{k}: mean recall {r:.2f}, all-required-found {a:.2f}, ~{tk:.0f} tokens/call (approx)")
