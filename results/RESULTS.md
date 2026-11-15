# Results (generated from results/traces.jsonl)

For each method and split: the last completed run of every task. Runs that died on an API error are excluded and counted in the last column.

| method | split | tasks | passed | prompt tokens / task | LLM calls / task | API-error runs excluded |
|---|---|---|---|---|---|---|
| bm25_top3 | learn | 18 | 3/18 | 6,469 | 6.7 | 2 |
| bm25_top3 | test | 10 | 2/10 | 5,622 | 6.3 | 0 |
| bm25_top5 | test | 10 | 4/10 | 10,835 | 5.9 | 0 |
| graph_5_N100 | test | 10 | 10/10 | 3,239 | 3.1 | 0 |
| graph_5_N1000 | test | 1 | 1/1 | 2,377 | 2.0 | 1 |
| graph_5_N300 | test | 0 | - | - | - | 5 |
| graph_k5 | test | 10 | 10/10 | 3,241 | 3.1 | 3 |
| preload | learn | 20 | 20/20 | 28,213 | 4.2 | 0 |
| preload | test | 10 | 10/10 | 29,352 | 4.3 | 0 |
| preload_all_N100 | test | 0 | - | - | - | 3 |
| preload_prereq | prereq | 0 | - | - | - | 1 |

## Per-task result on the held-out test tasks

P = passed, F = failed, - = no clean run.

| task | bm25_top3 | bm25_top5 | graph_5_N100 | graph_5_N1000 | graph_5_N300 | graph_k5 | preload | preload_all_N100 |
|---|---|---|---|---|---|---|---|---|
| T01 | P | P | P | P | - | P | P | - |
| T02 | F | F | P | - | - | P | P | - |
| T03 | F | F | P | - | - | P | P | - |
| T04 | F | F | P | - | - | P | P | - |
| T05 | F | F | P | - | - | P | P | - |
| T06 | F | P | P | - | - | P | P | - |
| T07 | F | F | P | - | - | P | P | - |
| T08 | P | P | P | - | - | P | P | - |
| T09 | F | F | P | - | - | P | P | - |
| T10 | F | P | P | - | - | P | P | - |
