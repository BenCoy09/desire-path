#!/usr/bin/env python3
"""Scale test: real 42 tools + N synthetic distractors.
Methods: preload_N (all tools offered) vs graph_k5_N (HydraDB selection, BM25 fallback over the big catalog).
Usage: python scripts/scale_test.py --sizes 100,300,1000 [--methods graph,preload]"""
import argparse, copy, json, pathlib, random, sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import run_agent as ra
import learn_graph as lg

DOMAINS = ["s3","gcs","azureblob","gdrive","dropbox","postgres","mysql","mongo","redis","sqlite",
 "github","gitlab","jira","linear","notion","slack","discord","gmail","calendar","stripe",
 "shopify","twilio","sendgrid","zendesk","hubspot","salesforce","airtable","figma","docker","k8s",
 "aws_lambda","cloudwatch","datadog","sentry","pagerduty","ftp","sftp","zip","pdf","csv"]
VERBS = ["read","write","list","search","delete","move","copy","create","update","get","fetch","upload","download","tree","edit"]
NOUNS = ["file","object","record","document","entity","page","message","issue","row","folder","bucket","channel","ticket","note","entry"]

def make_distractors(real, n, seed=7):
    rnd = random.Random(seed)
    real_names = {t["name"] for t in real}
    out, seen = [], set(real_names)
    while len(out) < n:
        d, v, nn = rnd.choice(DOMAINS), rnd.choice(VERBS), rnd.choice(NOUNS)
        name = f"{d}_{v}_{nn}"
        if name in seen:
            continue
        seen.add(name)
        t = copy.deepcopy(rnd.choice(real))      # copy shape and schema weight
        t["name"] = name
        t["id"] = f"synthetic__{name}"
        if "server" in t: t["server"] = "synthetic"
        if "description" in t:
            t["description"] = (f"{v.capitalize()} a {nn} in {d}. Supports filters, pagination and "
                                f"batch mode. Returns structured results for the {d} workspace.")
        t["synthetic"] = True
        out.append(t)
    return out

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", default="100,300,1000")
    ap.add_argument("--methods", default="graph,preload")
    ap.add_argument("--k", type=int, default=5)
    a = ap.parse_args()
    real = ra.load_catalog()
    db = lg.Hydra()
    out_file = ra.RESULTS / "traces.jsonl"
    tasks = [t for t in ra.TASKS if t["split"] == "test"]
    pool = ra.Pool()
    summary = []
    for n in [int(x) for x in a.sizes.split(",")]:
        catalog = real + make_distractors(real, n)
        pathlib.Path(ra.RESULTS / f"synth_catalog_{n}.json").write_text(json.dumps(catalog))
        bm = ra.Bm25(catalog)
        sel = lg.Selector(db.fetch_term, db.fetch_follow, catalog, bm)
        for m in a.methods.split(","):
            method = f"{m}_{a.k if m=='graph' else 'all'}_N{n}"
            res = []
            for t in tasks:
                tools, info = (sel.select(t["prompt"], a.k) if m == "graph" else (catalog, {}))
                tr = ra.run_task(t, tools, pool, method)
                tr["graph_info"], tr["catalog_size"] = info, len(catalog)
                with out_file.open("a") as f:
                    f.write(json.dumps(tr, ensure_ascii=False) + "\n")
                res.append(tr)
                print(f"N={n} {m} {t['id']} {'PASS' if tr['success'] else 'FAIL'} "
                      f"prompt_tok={tr['prompt_tokens']} {tr['error'][:80] if tr['error'] else ''}")
                if "HTTP 429" in (tr["error"] or ""):
                    print("quota hit, stopping this method"); break
            if res:
                p = sum(r["success"] for r in res)
                tok = sum(r["prompt_tokens"] for r in res) / len(res)
                summary.append((n + len(real), m, f"{p}/{len(res)}", round(tok)))
    pool.reset()
    print("\ncatalog  method   pass   mean_prompt_tokens")
    for row in summary:
        print(f"{row[0]:<8} {row[1]:<8} {row[2]:<6} {row[3]}")

if __name__ == "__main__":
    main()
