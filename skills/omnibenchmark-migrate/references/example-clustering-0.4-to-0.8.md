# Worked example: omni-clustering-benchmarks, 0.4.0 → 0.8.0

The clustering benchmark from the Omnibenchmark preprint (arXiv 2409.17038):
`omnibenchmark/clustering_example`, branch `update-to-0.4-full`, migrated on
branch `api-0.8`. 62 datasets from Gagolewski's clustering-benchmarks, five
clustering modules (48 methods), one metrics module (3 metrics), five
true-k−2 … true-k+2 runs per method. Conda, apptainer (oras) and envmodules
plans, identical apart from environments.

Modules move to the omnibenchmark org as `clustbench-<name>`; each gets an
`api-0.8` branch.

## Size

| | nodes | files compared |
|---|---|---|
| full grid, `ob run --dry` | 6573 | |
| slice (`fcps/atom`, `fcps/chainlink`) | 213 (217 jobs with gathers and manifests) | 212 |

Slice result: `compare_trees.py` → `different: 0`, nothing on one side only.

## Modules

Seven modules, one commit each for the CLI, all the same shape (fastcluster
shown). The data module also renamed `--dataset_name` to `--dataset`.

```diff
-    parser.add_argument('--data.matrix', type=str, …)
+    parser.add_argument('--data_matrix', type=str, …)
-    parser.add_argument('--output_dir', type=str, …)
-    parser.add_argument('--name', type=str, …, default='clustbench')
+    parser.add_argument('--output', action='append', default=[], …)
-    try:
-        args = parser.parse_args()
-    except:
-        parser.print_help()
-        sys.exit(0)
+    args, _ = parser.parse_known_args()
+    outputs = dict(o.split('=', 1) for o in args.output)
-    data = getattr(args, 'data.matrix')
+    data = args.data_matrix
-    np.savetxt(os.path.join(args.output_dir, f"{name}_ks_range.labels.gz"), …)
+    np.savetxt(outputs['clustering_predicted_ks_range'], …)
```

The `fcps` module is R (`argparse`); same change with
`parse_known_args()[[1]]`.

`clustbench-metrics` gained a second entrypoint, `summary`: the per-dataset
gather. It replaced the old `clustering_report` collector repo, whose Rmd
globbed `out/` for `clustbench.scores.gz` and parsed `stage/module/param`
triples.

## Plan

```diff
 version: "1.5.0"
+api_version: "0.8.0"
-metric_collectors:
-  - id: plotting
-    inputs: [metrics.scores]
-    …
   - id: data
     modules:
-      - id: clustbench
-        parameters:
-          - dataset_generator: "fcps"
-            dataset_name: ["atom", "chainlink", …]
-          - dataset_generator: "graves"
-            …
+      - id: fcps                       # one module per generator
+        parameters:
+          - dataset_generator: "fcps"  # duplicated: no {module.id} in parameter values
+            dataset: ["atom", "chainlink", …]
+      - id: graves
+        …
     outputs:
-      - id: data.matrix
-        path: "{dataset}.data.gz"
+      - id: data_matrix
+        path: "data.gz"
   - id: clustering
     inputs:
-      - data.matrix
+      - data_matrix
```

Plus two gather stages, `metrics_summary` (`group_by: data`) and `report`
(global, `path: report`, omni-quarto-report with `reports/report.Rmd` from the
plan repo). The oras and envmodules plans stop at `metrics_summary`: there is
no quarto image or easyconfig yet.

Paths, before and after, for one score file:

```
out/data/clustbench/.1f2b8e54/clustering/agglomerative/.388fd9c4/metrics/partition_metrics/.c1b81699/clustbench.scores.gz
out/data.fcps.3c92d668/clustering.agglomerative.388fd9c4/metrics.partition_metrics.c1b81699/scores.gz
```

The data hash changed (parameter renamed); the others did not.

## Validation command

```bash
python3 compare_trees.py out_04_slice out_08_slice \
  --rename-file clustbench.data.gz=data.gz \
  --rename-file clustbench.labels0.gz=labels0.gz \
  --rename-file clustbench_ks_range.labels.gz=ks_range.labels.gz \
  --rename-file clustbench.scores.gz=scores.gz \
  --rename-param dataset_name=dataset \
  --ignore-module data
```

`--ignore-module data` because `clustbench` became six modules; the
`dataset_generator`/`dataset` parameters still identify each data node.

## What went wrong on the way

| Symptom | Cause |
|---|---|
| `Entrypoint 'default' not found` at `ob run`, after `ob validate plan` passed | `entrypoint:` written on the module, not under `repository:` |
| Report failed: `non-numeric argument to binary operator` | `fcps` writes its header with R `write.table`, quoted: `"k=2"`. The old report never parsed k; the summary now strips the quotes |
| Cross-run analysis failed on `performances.tsv` | an R variable named `lineage` inside `transmute()`, shadowed by the table's `lineage` column |
| Filter picks stopped matching | renaming `dataset_name` changed the data nodes' hashes; re-read them from the dry-run Snakefile |

## Reports

- `reports/report.Rmd` (in the plan): one run. Scores at true k by method, and
  the change against true k when k is misspecified (the paper's Figure S5),
  from the `summary.tsv` tables.
- `reports/across_backends.Rmd` (in the plan, outside any run): the paper's
  Figure 2 B–E and S3–S4 comparisons (ARI, CPU time and max RSS against conda),
  over `out_<backend>_seed_<seed>_run_<run>` trees. The `Makefile` produces
  those trees and runs `ob collect performance` on each.
