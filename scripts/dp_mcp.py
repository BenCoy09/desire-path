#!/usr/bin/env python3
"""Desire Path MCP server: stdio, JSON-RPC 2.0, Python standard library only.

Lets an MCP client ask Desire Path which tools a task needs (and, optionally, teach it).
Environment:
  DESIRE_PATH_URL          API base URL (default: the public demo)
  DESIRE_PATH_ALLOW_TEACH  set to 1 to enable teach_tools (off by default: the demo graph is shared)
"""
import json, os, sys, urllib.error, urllib.parse, urllib.request

BASE = os.environ.get("DESIRE_PATH_URL", "https://desire-path.onrender.com").rstrip("/")
ALLOW_TEACH = os.environ.get("DESIRE_PATH_ALLOW_TEACH") == "1"
TIMEOUT = 90  # the free demo host can take about a minute to wake
VERSION = "0.1.0"

TOOLS = [
    {"name": "route_tools",
     "description": "Ask Desire Path which tools a task needs. Returns a short list of tool ids (server__name). "
                    "Load only those tool definitions instead of the whole catalog. If there is no confident match, load the full catalog.",
     "inputSchema": {"type": "object", "properties": {
         "task": {"type": "string", "description": "The task, in plain words."},
         "k": {"type": "integer", "description": "How many tools to return (1-20, default 5)."}}, "required": ["task"]}},
    {"name": "list_catalog",
     "description": "List every tool id Desire Path knows about (server__name).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "teach_tools",
     "description": "Teach Desire Path which tools a finished task actually used, in the order they were used. "
                    "Disabled unless DESIRE_PATH_ALLOW_TEACH=1, because the public demo graph is shared with everyone.",
     "inputSchema": {"type": "object", "properties": {
         "task": {"type": "string"},
         "tools": {"type": "array", "items": {"type": "string"}, "description": "Tool ids (server__name), in order of use."}},
         "required": ["task", "tools"]}},
]


def http(method, path, params=None, body=None):
    url = BASE + path + ("?" + urllib.parse.urlencode(params) if params else "")
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json", "User-Agent": "desire-path-mcp/" + VERSION})
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            return json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"error": "HTTP %d" % e.code}


def ok(text):
    return {"content": [{"type": "text", "text": text}], "isError": False}


def err(text):
    return {"content": [{"type": "text", "text": text}], "isError": True}


def call(name, a):
    try:
        if name == "route_tools":
            task = str(a.get("task", "")).strip()
            if not task:
                return err("task is required")
            k = max(1, min(int(a.get("k", 5)), 20))
            d = http("GET", "/select", {"task": task, "k": k})
            if d.get("error"):
                return err(str(d["error"]))
            if d.get("no_confident_match"):
                return ok("No confident match for this task. Load the full tool catalog.")
            ids = ["%s__%s" % (t.get("server"), t.get("name")) for t in d.get("tools", [])]
            return ok("Load only these tool definitions: %s (graph lookup took %s ms)" % (", ".join(ids), d.get("traversal_ms")))
        if name == "list_catalog":
            d = http("GET", "/tools")
            if d.get("error"):
                return err(str(d["error"]))
            return ok("%d tools: %s" % (len(d.get("tools", [])), ", ".join(d.get("tools", []))))
        if name == "teach_tools":
            if not ALLOW_TEACH:
                return err("Teaching is disabled. Set DESIRE_PATH_ALLOW_TEACH=1 (and point DESIRE_PATH_URL at your own instance if you do not want to change the shared demo).")
            d = http("POST", "/learn", body={"task": a.get("task", ""), "tools": a.get("tools") or []})
            if d.get("error"):
                return err(str(d["error"]))
            return ok("Taught. Routing before: %s. After: %s. Saved: %s" % (", ".join(d.get("before", [])), ", ".join(d.get("after", [])), d.get("persisted")))
        return err("unknown tool: %s" % name)
    except Exception as e:
        return err("request failed: %s: %s" % (type(e).__name__, str(e)[:200]))


def send(o):
    sys.stdout.write(json.dumps(o) + "\n")
    sys.stdout.flush()


def main():
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            m = json.loads(line)
        except Exception:
            continue
        mid, meth, p = m.get("id"), m.get("method"), m.get("params") or {}
        if mid is None:
            continue  # notifications need no reply
        try:
            if meth == "initialize":
                res = {"protocolVersion": p.get("protocolVersion", "2024-11-05"), "capabilities": {"tools": {}},
                       "serverInfo": {"name": "desire-path", "version": VERSION}}
            elif meth == "ping":
                res = {}
            elif meth == "tools/list":
                res = {"tools": TOOLS}
            elif meth == "tools/call":
                res = call(p.get("name"), p.get("arguments") or {})
            else:
                send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": "method not found: %s" % meth}})
                continue
            send({"jsonrpc": "2.0", "id": mid, "result": res})
        except Exception as e:
            send({"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}})


if __name__ == "__main__":
    main()
