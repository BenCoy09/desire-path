cd ~/desire-path
echo "== git"; git log --oneline | head -8; git status --short | head -8
echo "== scripts"; ls scripts site docs 2>/dev/null
echo "== running"; pgrep -af "run_agent|queue.sh|graph-node" | cut -c1-90
echo "== results"
python3 - <<'PY'
import json, collections
d = collections.defaultdict(list)
for l in open('results/traces.jsonl'):
    r = json.loads(l); d[(r['method'], r['split'])].append(r)
for (m, s), rs in sorted(d.items()):
    n = len(rs)
    print(m, s, sum(r['success'] for r in rs), '/', n, '| tok', round(sum(r['prompt_tokens'] for r in rs)/n), '| calls', round(sum(r['llm_calls'] for r in rs)/n, 1), '| err', sum(bool(r['error']) for r in rs))
PY
echo "== key leak check (should be 0)"; git log -p --all | grep -c "AIza"
