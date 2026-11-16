# Migrating to api 0.8.0 (from 0.4.0–0.7.0)

Read with the method in `SKILL.md`. Worked example:
[`example-clustering-0.4-to-0.8.md`](example-clustering-0.4-to-0.8.md).

A plan below 0.7.0 also picks up the 0.7.0 changes (shared output ids expand
instead of binding one producer; diamond inputs become joins). See
`omnibenchmark-plan/references/migration-0.4-to-0.7.md`; the node counts in
step 5 will show them.

## What changes

| Area | Before | 0.8.0 |
|---|---|---|
| Output layout | `stage/module/.hash/` per node | `stage.module.hash/` per node, no `.default` for a node without parameters; readable names in `out/by-params/` |
| Module outputs | module builds `{output_dir}/{name}…` | ob passes `--output <id>=<abs path>` per declared output |
| Stage and module ids | free-form | `[A-Za-z_][A-Za-z0-9_]*` |
| `metric_collectors:` | supported | rejected; use a stage with `gather:` |
| Gather module input | `--<id> p1 p2 …` | `--from-files lineage.json` (manifest v2) |
| `gather: {group_by: S}` | one group per S module | one group per S node; the gather is a child of that node and may declare `inputs:` |
| `{dataset}` in paths | the root module id | deprecated; the node directory already carries the lineage |

`--output_dir` and `--name` are still passed until api 0.10. Modules must
tolerate them, and should not use them.

The gather rows need an `ob` with the 0.8.0 gather work (omnibenchmark PR
#416). On an older `ob`, `metric_collectors:` still loads on a 0.8.0 plan;
check the installed version with the CLI skill.

## Conventions (beyond what ob enforces)

- **Output ids are identifiers too** (`data_matrix`, not `data.matrix`). ob
  accepts dots, but a dotted id becomes a dotted input flag, which forces
  `getattr(args, "data.matrix")` in Python and `args[["data.matrix"]]` in R.
  Rename in the same migration, since every path changes anyway, and touch
  every consumer's input flag.
- **Output paths are constant file names** (`scores.gz`). The node directory
  is the identity; a `{dataset}` or `{name}` prefix only duplicates it.

## Modules

```bash
grep -nE "parse_args\(|output_dir|args.name|args\[\['name|getattr\(args, '[a-z_]+\.|sys.exit\(0\)" *.py *.R
```

- Parse with `parse_known_args`. `ob` passes flags the module does not declare
  (`--output_dir`, `--name`), and strict parsing rejects them. The common
  `try: parse_args() except: print_help(); sys.exit(0)` is worse: the job
  exits 0 having written nothing, and Snakemake reports a missing output
  instead of the argparse error. Remove the `try`.
- Add `--output` (append) and write each output to `outputs[id]`.
- Rename input flags to the new output ids (`--data_matrix`).
- Delete `--output_dir` and `--name` from the parser.

```python
parser.add_argument("--output", action="append", default=[])
args, _ = parser.parse_known_args()
outputs = dict(o.split("=", 1) for o in args.output)   # split on the first '=' only
```

```r
parser$add_argument("--output", action = "append", default = list())
args <- parser$parse_known_args()[[1]]          # [[1]]: known args; [[2]]: the rest
kv <- regmatches(unlist(args$output), regexpr("=", unlist(args$output)), invert = TRUE)
outputs <- setNames(sapply(kv, `[`, 2), sapply(kv, `[`, 1))
```

## Plan

1. `api_version: "0.8.0"` next to `version:`; bump `version:` too (the next
   run then refuses an out dir recorded under the old version, which is what
   you want).
2. Rename stage, module and output ids to identifiers; rename `inputs:`
   entries to match.
3. Output paths: constant file names; drop `{dataset}`/`{name}`.
4. Repin every module to its migrated commit.
5. A named entrypoint goes **under `repository:`**. Placed on the module
   itself, `entrypoint:` passes `ob validate plan` and is ignored at run time
   (`Entrypoint 'default' not found`).
6. Replace `metric_collectors:` with gather stages (below).

Template variables are substituted in output paths only. A parameter value
`"{module.id}"` reaches the module as that literal text. A module that needs
its own id (one data module per source, same code) gets it as an ordinary
single-valued parameter, duplicated next to the id. Do not read it from
`--name`.

## Collectors become gathers

A 0.4 collector (one terminal node globbing `out/`) maps to two gather
stages. Two levels, because a global report over raw scores re-implements
grouping that `group_by` already does:

```yaml
  - id: metrics_summary          # one tidy table per dataset
    gather: {from: metrics_scores, group_by: data}
    modules:
      - id: summary
        repository: {url: …, commit: …, entrypoint: summary}
    outputs:
      - id: metrics_summary
        path: summary.tsv

  - id: report                   # one report over every table
    gather: {from: metrics_summary, path: report}   # out/report/, no hash
    modules:
      - id: quarto
        repository: {url: …/omni-quarto-report, commit: …}
        parameters:
          - template: reports/report.Rmd            # lives in the plan repo
    outputs:
      - id: report_html
        path: report.html
```

The summary module reads the manifest and labels each row from its lineage:

```python
for member in json.load(open(args.from_files))["members"]:
    by_stage = {e["stage"]: e for e in member["lineage"]}   # look up by stage, not position
    dataset = by_stage["data"]["parameters"]["dataset"]
    method = by_stage["clustering"]["module"]
    path = member["files"]["metrics_scores"]
```

- A gather module runs from **its own checkout**, not from `out/`. Anything it
  renders (knitr intermediates, figures) goes next to `outputs[id]`; a
  template in the plan repo is found by walking up from the output path.
- A collector that globbed the tree and parsed directory names
  (`stage/module/param` triples, `parameters.json` beside them, hash-length
  heuristics) cannot be ported, only rewritten. Keep its plots; replace its
  data loading.
- A report environment (quarto + R) exists for conda only unless someone
  builds the image or easyconfig. Plans for other backends can stop at the
  summary stage.

Analyses across runs (backends, seeds, replicates) stay outside the plan.
They read each run's summary tables plus `ob collect performance -o <out>`
(`performances.tsv`; its JSON `params` column holds parameter values by
stage). In R, do not name a variable `lineage` inside dplyr verbs:
`performances.tsv` has a column of that name and it wins.

## Slice filter

Picks name modules and parameter hashes. Read the hashes off the rules of a
dry run:

```bash
ob run plan.yml --dirty --dry --out-dir out_dry
grep -n 'cli_args="--dataset atom' -B8 out_dry/Snakefile | grep -o 'data\.[a-z_]*\.[0-9a-f]*'
```

```yaml
picks:
  data: {fcps: [19e07dfb, 3c92d668]}   # atom, chainlink
  clustering: {'*': all}
  metrics: {'*': all}
  metrics_summary: {'*': all}
  report: {'*': all}
```

## Comparing

`compare_trees.py` reads both layouts. Typical flags for this migration:
`--rename-file` for every output whose file name lost its `{dataset}`/`{name}`
prefix, `--rename-param` for renamed parameters, `--ignore-module <stage>` for
a stage whose modules were split or merged.
