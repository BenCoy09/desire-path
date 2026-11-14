#!/usr/bin/env python3
"""Check the Gemini key and find a model that can do tool calling."""
import json, os, pathlib, urllib.request, urllib.error

env = pathlib.Path.home() / ".desire-path.env"
KEY = None
for line in env.read_text().splitlines():
    if line.startswith("GEMINI_API_KEY="):
        KEY = line.split("=", 1)[1].strip().strip('"').strip("'")
if not KEY:
    raise SystemExit("GEMINI_API_KEY not found in ~/.desire-path.env")

BASE = "https://generativelanguage.googleapis.com/v1beta"
HDR = {"x-goog-api-key": KEY, "Content-Type": "application/json"}


def call(url, body=None):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode() if body else None, headers=HDR)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read())
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:400]
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}"


status, data = call(f"{BASE}/models?pageSize=200")
print("list models status:", status)
if status != 200:
    raise SystemExit(f"key or endpoint problem: {data}")

names = [m["name"].split("/", 1)[1] for m in data.get("models", [])
         if "generateContent" in m.get("supportedGenerationMethods", [])]
flash = [n for n in names if "flash" in n]
print(f"{len(names)} models support generateContent; flash-type ones:")
for n in flash[:15]:
    print("  ", n)

tool = {"functionDeclarations": [{
    "name": "read_file",
    "description": "Read a text file and return its contents.",
    "parameters": {"type": "object",
                   "properties": {"path": {"type": "string"}},
                   "required": ["path"]}}]}
body = {"contents": [{"role": "user", "parts": [
            {"text": "Read the contents of notes.txt"}]}],
        "tools": [tool]}

tried = 0
for n in flash:
    if "image" in n or "tts" in n or "live" in n:
        continue
    tried += 1
    if tried > 3:
        break
    status, out = call(f"{BASE}/models/{n}:generateContent", body)
    if status != 200:
        print(f"model {n}: HTTP {status} {str(out)[:200]}")
        continue
    parts = out["candidates"][0]["content"].get("parts", [])
    fc = [p["functionCall"] for p in parts if "functionCall" in p]
    usage = out.get("usageMetadata", {})
    print(f"model {n}: HTTP 200, tool call returned: {bool(fc)}, usage: {usage}")
    if fc:
        print("   call:", fc[0])
        print(f"WORKING MODEL: {n}")
        break
