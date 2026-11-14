#!/usr/bin/env python3
"""Find a pinned Gemini model that does tool calling; save it as GEMINI_MODEL."""
import json, pathlib, time, urllib.request, urllib.error

env = pathlib.Path.home() / ".desire-path.env"
lines = env.read_text().splitlines()
KEY = next(l.split("=", 1)[1].strip().strip('"').strip("'")
           for l in lines if l.startswith("GEMINI_API_KEY="))
BASE = "https://generativelanguage.googleapis.com/v1beta"
HDR = {"x-goog-api-key": KEY, "Content-Type": "application/json"}
CANDIDATES = ["gemini-2.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]

body = {
    "contents": [{"role": "user", "parts": [{"text": "Read the contents of notes.txt"}]}],
    "tools": [{"functionDeclarations": [{
        "name": "read_file",
        "description": "Read a text file and return its contents.",
        "parameters": {"type": "object",
                       "properties": {"path": {"type": "string"}},
                       "required": ["path"]}}]}],
}


def call(model):
    for attempt in range(3):
        req = urllib.request.Request(
            f"{BASE}/models/{model}:generateContent",
            data=json.dumps(body).encode(), headers=HDR)
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return 200, json.loads(r.read())
        except urllib.error.HTTPError as e:
            msg = e.read().decode()[:200].replace("\n", " ")
            if e.code in (429, 503) and attempt < 2:
                time.sleep(5 * (attempt + 1))
                continue
            return e.code, msg
        except Exception as e:
            return 0, f"{type(e).__name__}: {e}"
    return 0, "retries exhausted"


chosen = None
for m in CANDIDATES:
    status, out = call(m)
    if status != 200:
        print(f"{m}: HTTP {status} {str(out)[:160]}")
        continue
    parts = out["candidates"][0]["content"].get("parts", [])
    fc = [p["functionCall"] for p in parts if "functionCall" in p]
    print(f"{m}: HTTP 200, tool call: {bool(fc)}, args: {fc[0]['args'] if fc else None}")
    if fc and not chosen:
        chosen = m

if chosen:
    lines = [l for l in lines if not l.startswith("GEMINI_MODEL=")]
    lines.append(f"GEMINI_MODEL={chosen}")
    env.write_text("\n".join(lines) + "\n")
    env.chmod(0o600)
    print(f"PINNED MODEL: {chosen} (saved to ~/.desire-path.env)")
else:
    print("No candidate did tool calling; paste this output to Claude")
