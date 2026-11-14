import os, json, time, urllib.request, urllib.error
env = {}
for l in open(os.path.expanduser("~/.desire-path.env")):
    l = l.strip().removeprefix("export ")
    if "=" in l and not l.startswith("#"):
        k, v = l.split("=", 1); env[k.strip()] = v.strip().strip('"').strip("'")
url = f"https://generativelanguage.googleapis.com/v1beta/models/{env['GEMINI_MODEL']}:generateContent"
while True:
    req = urllib.request.Request(url, json.dumps({"contents": [{"parts": [{"text": "hi"}]}]}).encode(),
          {"Content-Type": "application/json", "x-goog-api-key": env["GEMINI_API_KEY"]})
    try:
        urllib.request.urlopen(req); print("quota back", flush=True); break
    except urllib.error.HTTPError as e:
        print(time.strftime("%H:%M"), e.code, "waiting", flush=True); time.sleep(600)
