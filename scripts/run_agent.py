#!/usr/bin/env python3
"""Real agent runner: Gemini + real MCP servers. Records every trace.

Usage:
  python scripts/run_agent.py --method preload            (all tools every call)
  python scripts/run_agent.py --method bm25 --k 5         (BM25 top-k tools)
  options: --tasks L01,L04  --split learn|test  --limit N  --rerun
Success is checked by code (answer text, files, memory), never by an LLM judge.
Traces are appended to results/traces.jsonl; finished tasks are skipped on rerun.
"""
import argparse, json, math, os, pathlib, queue, re, shutil, subprocess, sys
import threading, time, urllib.request, urllib.error
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS_DIR = ROOT / "data" / "tools"
RESULTS = ROOT / "results"
SANDBOX = "/tmp/dp-sandbox"
MEMORY_FILE = "/tmp/dp-memory.json"
MAX_STEPS = 8
RESULT_CAP = 3000


def load_env():
    env = {}
    p = pathlib.Path.home() / ".desire-path.env"
    if p.exists():
        for line in p.read_text().splitlines():
            line = line.strip()
            if "=" in line and not line.startswith("#"):
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    return env


ENV = load_env()
KEY = ENV.get("GEMINI_API_KEY")
MODEL = ENV.get("GEMINI_MODEL")
MIN_INTERVAL = float(os.environ.get("DP_MIN_INTERVAL", "4"))
BASE = "https://generativelanguage.googleapis.com/v1beta"

# ---------------------------------------------------------------- fixture
FIXTURE = {
    "notes.txt": "Meeting moved to Thursday.\nBudget code: ZX-4471.\nOwner: Priya.\n",
    "plan.txt": "Launch date: March 9.\nBudget code: QW-1180.\nOwner: Marcus.\n",
    "todo.txt": "1. buy milk\n2. call Dana\n3. file taxes\n",
    "a.txt": "alpha-7731\n",
    "b.txt": "bravo-2208\n",
    "c.txt": "charlie-9054\n",
    "project/readme.md": "# Project Orion\nStatus: active\n",
    "project/src/main.py": "print('hello')\n",
    "project/src/util.js": "module.exports = {}\n",
    "project/src/data.csv": "id,val\n1,5\n",
    "logs/app.log": "INFO start\nERROR disk full\nINFO stop\n",
    "docs/guide.md": "# Guide\nSupport email: help@orion.example\n",
    "docs/faq.md": "# FAQ\nRefund window: 30 days\n",
}


def reset_fixture():
    shutil.rmtree(SANDBOX, ignore_errors=True)
    for rel, text in FIXTURE.items():
        p = pathlib.Path(SANDBOX) / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    (pathlib.Path(SANDBOX) / "archive").mkdir(exist_ok=True)
    try:
        os.remove(MEMORY_FILE)
    except FileNotFoundError:
        pass


# ---------------------------------------------------------------- tasks
def T(tid, fam, split, prompt, **check):
    return {"id": tid, "family": fam, "split": split, "prompt": prompt, "check": check}


TASKS = [
    T("L01", "read", "learn", "What is the budget code in notes.txt? Answer with just the code.", answer_contains=["ZX-4471"]),
    T("L02", "read", "learn", "Who is the owner listed in plan.txt?", answer_contains=["Marcus"]),
    T("L03", "read", "learn", "What is the support email in docs/guide.md?", answer_contains=["help@orion.example"]),
    T("L04", "write", "learn", "Create a folder called reports and save a file reports/summary.txt containing the text: Q3 done", files={"reports/summary.txt": {"contains": ["Q3 done"]}}),
    T("L05", "write", "learn", "Create a folder called exports and save a file exports/status.txt containing the text: all green", files={"exports/status.txt": {"contains": ["all green"]}}),
    T("L06", "remember", "learn", "Read todo.txt and store each task as a separate memory entity.", memory_contains=["buy milk", "call Dana", "file taxes"]),
    T("L07", "remember", "learn", "Read plan.txt and store its launch date and owner in memory as an entity called Plan.", memory_contains=["March 9", "Marcus"]),
    T("L08", "find", "learn", "Find the file named readme.md somewhere in the sandbox and tell me the project name.", answer_contains=["Orion"]),
    T("L09", "find", "learn", "Find the file named faq.md somewhere in the sandbox and tell me the refund window.", answer_contains=["30 days"]),
    T("L10", "combine", "learn", "Read a.txt and b.txt and write both of their codes into combined.txt in the sandbox root.", files={"combined.txt": {"contains": ["alpha-7731", "bravo-2208"]}}),
    T("L11", "combine", "learn", "Read b.txt and c.txt and write both of their codes into merged.txt in the sandbox root.", files={"merged.txt": {"contains": ["bravo-2208", "charlie-9054"]}}),
    T("L12", "listdir", "learn", "Which file in project/src is a Python file?", answer_contains=["main.py"]),
    T("L13", "listdir", "learn", "Which file in project/src is a CSV file?", answer_contains=["data.csv"]),
    T("L14", "recall", "learn", "Remember that Dana's manager is Eli, then look it up in memory and tell me who Dana's manager is.", memory_contains=["Eli"], answer_contains=["Eli"]),
    T("L15", "recall", "learn", "Remember that Priya's team is Platform, then look it up in memory and tell me Priya's team.", memory_contains=["Platform"], answer_contains=["Platform"]),
    T("L16", "move", "learn", "Move notes.txt into the archive folder.", exists=["archive/notes.txt"], not_exists=["notes.txt"]),
    T("L17", "move", "learn", "Move todo.txt into the archive folder.", exists=["archive/todo.txt"], not_exists=["todo.txt"]),
    T("L18", "edit", "learn", "In project/readme.md replace the word Orion with Lyra.", files={"project/readme.md": {"contains": ["Lyra"], "not_contains": ["Orion"]}}),
    T("L19", "edit", "learn", "In plan.txt change the owner from Marcus to Ines.", files={"plan.txt": {"contains": ["Ines"], "not_contains": ["Marcus"]}}),
    T("L20", "read", "learn", "According to notes.txt, which weekday was the meeting moved to?", answer_contains=["Thursday"]),
    T("T01", "read", "test", "What launch date is written in plan.txt?", answer_contains=["March 9"]),
    T("T02", "write", "test", "Create a folder called backups and save a file backups/note.txt containing the text: nightly ok", files={"backups/note.txt": {"contains": ["nightly ok"]}}),
    T("T03", "remember", "test", "Read notes.txt and store its budget code and owner in memory as an entity called Notes.", memory_contains=["ZX-4471", "Priya"]),
    T("T04", "find", "test", "Find the file named guide.md somewhere in the sandbox and tell me the support email.", answer_contains=["help@orion.example"]),
    T("T05", "combine", "test", "Read a.txt and c.txt and write both of their codes into joined.txt in the sandbox root.", files={"joined.txt": {"contains": ["alpha-7731", "charlie-9054"]}}),
    T("T06", "listdir", "test", "Which file in project/src is a JavaScript file?", answer_contains=["util.js"]),
    T("T07", "recall", "test", "Remember that Eli's team is Growth, then look it up in memory and tell me Eli's team.", memory_contains=["Growth"], answer_contains=["Growth"]),
    T("T08", "move", "test", "Move plan.txt into the archive folder.", exists=["archive/plan.txt"], not_exists=["plan.txt"]),
    T("T09", "edit", "test", "In docs/faq.md change 30 days to 45 days.", files={"docs/faq.md": {"contains": ["45 days"], "not_contains": ["30 days"]}}),
    T("T10", "filter", "test", "Read logs/app.log and write only the ERROR lines into reports/errors.txt (create the folder if needed).", files={"reports/errors.txt": {"contains": ["ERROR disk full"], "not_contains": ["INFO"]}}),
]


def evaluate(spec, final):
    why = []
    low = (final or "").lower()
    for s in spec.get("answer_contains", []):
        if s.lower() not in low:
            why.append(f"answer missing {s!r}")
    for rel, rule in spec.get("files", {}).items():
        p = pathlib.Path(SANDBOX) / rel
        if not p.is_file():
            why.append(f"file missing {rel}")
            continue
        txt = p.read_text(errors="replace")
        for s in rule.get("contains", []):
            if s not in txt:
                why.append(f"{rel} missing {s!r}")
        for s in rule.get("not_contains", []):
            if s in txt:
                why.append(f"{rel} still has {s!r}")
    for rel in spec.get("exists", []):
        if not (pathlib.Path(SANDBOX) / rel).exists():
            why.append(f"missing {rel}")
    for rel in spec.get("not_exists", []):
        if (pathlib.Path(SANDBOX) / rel).exists():
            why.append(f"still exists {rel}")
    mem = ""
    try:
        mem = pathlib.Path(MEMORY_FILE).read_text(errors="replace")
    except FileNotFoundError:
        pass
    for s in spec.get("memory_contains", []):
        if s.lower() not in mem.lower():
            why.append(f"memory missing {s!r}")
    return (not why), ("; ".join(why) or "ok")


# ---------------------------------------------------------------- MCP client
class Mcp:
    def __init__(self, cmd, env_extra=None):
        env = dict(os.environ)
        env.update(env_extra or {})
        self.p = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=subprocess.DEVNULL, text=True, bufsize=1, env=env)
        self.q = queue.Queue()
        self.n = 0
        threading.Thread(target=self._read, daemon=True).start()
        self._rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                                 "clientInfo": {"name": "desire-path", "version": "0.1"}}, timeout=120)
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _read(self):
        for line in self.p.stdout:
            self.q.put(line)

    def _send(self, o):
        self.p.stdin.write(json.dumps(o) + "\n")
        self.p.stdin.flush()

    def _rpc(self, method, params, timeout=60):
        self.n += 1
        i = self.n
        self._send({"jsonrpc": "2.0", "id": i, "method": method, "params": params})
        end = time.time() + timeout
        while True:
            left = end - time.time()
            if left <= 0:
                raise TimeoutError(method)
            try:
                line = self.q.get(timeout=left)
            except queue.Empty:
                raise TimeoutError(method)
            try:
                m = json.loads(line)
            except ValueError:
                continue
            if m.get("id") == i and "method" not in m:
                return m

    def call_tool(self, name, args):
        m = self._rpc("tools/call", {"name": name, "arguments": args}, timeout=60)
        if "error" in m:
            return True, json.dumps(m["error"])[:RESULT_CAP]
        r = m.get("result", {})
        text = "\n".join(c.get("text", "") for c in r.get("content", []) if c.get("type") == "text")
        return bool(r.get("isError")), text[:RESULT_CAP]

    def close(self):
        try:
            self.p.kill()
        except Exception:
            pass


SERVERS = {
    "filesystem": (["npx", "-y", "@modelcontextprotocol/server-filesystem", SANDBOX], {}),
    "memory": (["npx", "-y", "@modelcontextprotocol/server-memory"], {"MEMORY_FILE_PATH": MEMORY_FILE}),
    "everything": (["npx", "-y", "@modelcontextprotocol/server-everything"], {}),
    "thinking": (["npx", "-y", "@modelcontextprotocol/server-sequential-thinking"], {}),
}


class Pool:
    def __init__(self):
        self.s = {}

    def get(self, name):
        if name not in self.s:
            cmd, env = SERVERS[name]
            self.s[name] = Mcp(cmd, env)
        return self.s[name]

    def reset(self):
        for m in self.s.values():
            m.close()
        self.s = {}


# ---------------------------------------------------------------- tools
def load_catalog():
    cat = []
    for p in sorted(TOOLS_DIR.glob("*.json")):
        for t in json.loads(p.read_text()):
            cat.append({"id": f"{p.stem}__{t['name']}", "server": p.stem, "name": t["name"],
                        "description": t.get("description") or "",
                        "schema": t.get("inputSchema") or {}, "chars": len(json.dumps(t))})
    return cat


def clean_schema(s):
    if not isinstance(s, dict):
        return {"type": "string"}
    if "type" not in s:
        for k in ("anyOf", "oneOf"):
            if s.get(k):
                c = clean_schema(s[k][0])
                if s.get("description"):
                    c["description"] = str(s["description"])[:400]
                return c
    t = s.get("type")
    if isinstance(t, list):
        t = next((x for x in t if x != "null"), "string")
    if t not in ("string", "number", "integer", "boolean", "array", "object"):
        t = "object" if "properties" in s else "string"
    out = {"type": t}
    if s.get("description"):
        out["description"] = str(s["description"])[:400]
    if t == "object":
        props = {k: clean_schema(v) for k, v in (s.get("properties") or {}).items()}
        out["properties"] = props
        req = [r for r in (s.get("required") or []) if r in props]
        if req:
            out["required"] = req
    if t == "array":
        out["items"] = clean_schema(s.get("items") or {"type": "string"})
    if "enum" in s and all(isinstance(x, str) for x in s["enum"]):
        out["enum"] = s["enum"]
    return out


def decl(t):
    d = {"name": t["id"], "description": t["description"]}
    sc = clean_schema(t["schema"])
    if sc.get("type") == "object" and sc.get("properties"):
        d["parameters"] = sc
    return d


def toks(s):
    return re.findall(r"[a-z0-9]+", s.lower())


class Bm25:
    def __init__(self, catalog):
        self.cat = catalog
        self.docs = [toks((t["name"] + " ") * 2 + t["description"]) for t in catalog]
        self.N = len(self.docs)
        self.avgdl = sum(len(d) for d in self.docs) / self.N
        self.df = Counter()
        for d in self.docs:
            self.df.update(set(d))

    def top(self, query, k):
        def score(i, k1=1.5, b=0.75):
            tf = Counter(self.docs[i])
            sc = 0.0
            for q in toks(query):
                if q in tf:
                    idf = math.log(1 + (self.N - self.df[q] + 0.5) / (self.df[q] + 0.5))
                    sc += idf * tf[q] * (k1 + 1) / (tf[q] + k1 * (1 - b + b * len(self.docs[i]) / self.avgdl))
            return sc
        order = sorted(range(self.N), key=lambda i: -score(i))[:k]
        return [self.cat[i] for i in order]


# ---------------------------------------------------------------- Gemini
_last = [0.0]


def gemini(body):
    url = f"{BASE}/models/{MODEL}:generateContent"
    hdr = {"x-goog-api-key": KEY, "Content-Type": "application/json"}
    for attempt in range(6):
        wait = MIN_INTERVAL - (time.time() - _last[0])
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
        req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=hdr)
        try:
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:300].replace("\n", " ")
            if e.code in (429, 500, 503) and attempt < 5:
                time.sleep(min(60, 8 * 2 ** attempt))
                continue
            raise RuntimeError(f"HTTP {e.code}: {msg}")
        except (urllib.error.URLError, TimeoutError) as e:
            if attempt < 5:
                time.sleep(5 * (attempt + 1))
                continue
            raise RuntimeError(f"network: {e}")


SYSTEM = ("You are a tool-using assistant. The sandbox directory is /tmp/dp-sandbox; "
          "always use absolute paths under it. Complete the task using the provided tools, "
          "then reply with a short final answer.")


def run_task(task, tools, pool, method):
    reset_fixture()
    pool.reset()
    decls = [decl(t) for t in tools]
    by_id = {t["id"]: t for t in tools}
    body_tools = [{"functionDeclarations": decls}] if decls else []
    contents = [{"role": "user", "parts": [{"text": task["prompt"]}]}]
    tr = {"task_id": task["id"], "family": task["family"], "split": task["split"],
          "method": method, "model": MODEL, "prompt": task["prompt"],
          "offered_tools": [t["id"] for t in tools], "calls": [], "final": "",
          "llm_calls": 0, "prompt_tokens": 0, "completion_tokens": 0,
          "def_chars": 0, "note": "", "error": ""}
    t0 = time.time()
    try:
        for step in range(MAX_STEPS):
            out = gemini({"systemInstruction": {"parts": [{"text": SYSTEM}]},
                          "contents": contents, "tools": body_tools})
            tr["llm_calls"] += 1
            u = out.get("usageMetadata", {})
            tr["prompt_tokens"] += u.get("promptTokenCount", 0)
            tr["completion_tokens"] += u.get("candidatesTokenCount", 0)
            tr["def_chars"] += len(json.dumps(decls))
            cands = out.get("candidates") or []
            if not cands:
                tr["note"] = "no candidates"
                break
            parts = (cands[0].get("content") or {}).get("parts", [])
            calls = [p["functionCall"] for p in parts if "functionCall" in p]
            if not calls:
                tr["final"] = "".join(p.get("text", "") for p in parts
                                      if "text" in p and not p.get("thought"))
                break
            contents.append({"role": "model", "parts": parts})
            resp = []
            for c in calls:
                name, args = c["name"], c.get("args") or {}
                if name not in by_id:
                    err, res = True, f"unknown tool {name}"
                else:
                    t = by_id[name]
                    try:
                        err, res = pool.get(t["server"]).call_tool(t["name"], args)
                    except Exception as e:
                        err, res = True, f"{type(e).__name__}: {e}"
                tr["calls"].append({"idx": len(tr["calls"]), "tool": name, "args": args,
                                    "result": res, "error": err})
                resp.append({"functionResponse": {"name": name,
                             "response": {"error" if err else "result": res}}})
            contents.append({"role": "user", "parts": resp})
        else:
            tr["note"] = "max steps"
    except Exception as e:
        tr["error"] = f"{type(e).__name__}: {e}"
    tr["latency_s"] = round(time.time() - t0, 1)
    ok, why = evaluate(task["check"], tr["final"])
    tr["success"] = bool(ok and not tr["error"])
    tr["check_detail"] = why
    pool.reset()
    return tr


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", default="preload", choices=["preload", "bm25"])
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--tasks", default="")
    ap.add_argument("--split", default="")
    ap.add_argument("--rerun", action="store_true")
    a = ap.parse_args()
    if not KEY or not MODEL:
        sys.exit("GEMINI_API_KEY / GEMINI_MODEL missing in ~/.desire-path.env")
    catalog = load_catalog()
    if not catalog:
        sys.exit(f"no tool files in {TOOLS_DIR}")
    method = "preload" if a.method == "preload" else f"bm25_top{a.k}"
    bm = Bm25(catalog)
    RESULTS.mkdir(exist_ok=True)
    out_file = RESULTS / "traces.jsonl"
    done = set()
    if out_file.exists() and not a.rerun:
        for line in out_file.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if not r.get("error"):
                done.add((r["task_id"], r["method"]))
    want = [x for x in a.tasks.split(",") if x]
    todo = [t for t in TASKS
            if (not want or t["id"] in want) and (not a.split or t["split"] == a.split)
            and (t["id"], method) not in done]
    if a.limit:
        todo = todo[:a.limit]
    print(f"model {MODEL} | method {method} | {len(todo)} tasks to run")
    pool = Pool()
    results = []
    for t in todo:
        tools = catalog if a.method == "preload" else bm.top(t["prompt"], a.k)
        tr = run_task(t, tools, pool, method)
        with out_file.open("a") as f:
            f.write(json.dumps(tr, ensure_ascii=False) + "\n")
        results.append(tr)
        used = ",".join(c["tool"].split("__", 1)[-1] for c in tr["calls"])
        tail = "" if tr["success"] else f" | {tr['error'] or tr['check_detail']}"
        print(f"{t['id']} {'PASS' if tr['success'] else 'FAIL'} llm={tr['llm_calls']} "
              f"prompt_tok={tr['prompt_tokens']} tools=[{used}]{tail}")
        if "HTTP 429" in tr["error"]:
            print("quota hit: stopping. Rerun later; finished tasks are skipped.")
            break
    pool.reset()
    if results:
        n = len(results)
        print(f"--- {method}: {sum(r['success'] for r in results)}/{n} passed | "
              f"mean prompt tokens {sum(r['prompt_tokens'] for r in results) / n:.0f} | "
              f"mean LLM calls {sum(r['llm_calls'] for r in results) / n:.1f}")


if __name__ == "__main__":
    main()
