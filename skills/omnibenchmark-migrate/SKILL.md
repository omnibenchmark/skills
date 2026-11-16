---
name: omnibenchmark-migrate
description: "Migrate an Omnibenchmark benchmark to a newer api_version, and prove the migration changed no result. Currently covers 0.4.0–0.7.0 → 0.8.0 (identifier ids, flat output layout, --output id=PATH named outputs, metric_collectors replaced by gather stages, gather modules reading --from-files lineage.json). The method is version-independent: baseline run of the old plan, port modules and plan, slice the new plan with --filter, compare both output trees by lineage with scripts/compare_trees.py. Use when a plan's api_version is older than the one wanted, when `ob validate plan` rejects a field after a bump (metric_collectors, dotted ids), when a module fails with a missing output or a KeyError on its outputs after the bump, when a collector or report must become a gather, or when asked whether a migrated benchmark still gives the same numbers."
---

# Migrating a benchmark to a newer api version

An api bump can change output paths, module CLIs and plan keywords at once.
A migration is done when the new plan reproduces the old plan's outputs file
for file on a slice of the benchmark, not when `ob validate plan` passes.

## Which version guide

| From → to | Guide |
|---|---|
| 0.4.0–0.7.0 → **0.8.0** | [`references/to-0.8.md`](references/to-0.8.md); worked example [`references/example-clustering-0.4-to-0.8.md`](references/example-clustering-0.4-to-0.8.md) |
| 0.4.0 → 0.7.0 | `omnibenchmark-plan/references/migration-0.4-to-0.7.md` |

Going across several versions, read every guide on the way; do the
migration once, to the target.

A plan with no `api_version:` key is 0.4.0.

## Method

Work on local clones and pin local commits (`url: /abs/path`, `commit: <sha>`,
run with `--dirty`). Push and repin to public URLs only after step 6 passes.

### 1. Baseline before touching anything

Keep the old plan runnable in its own worktree, and run a small slice of it
with the **same** `ob` you will use for the new plan:

```bash
git worktree add ../plan_old <old commit>
# trim the data stage's parameter list to 1–2 small datasets, then:
ob run plan_slice.yml --out-dir out_old_slice --cores 8 -k
```

Trim the YAML rather than using `--filter` here. Filter picks are parameter
hashes, and those change when parameter names or module ids change.

### 2. Read the version guide

List what the guide says changes, then grep each module repo and the plan
for every item (the guide gives the grep). Decide the conventions that go
beyond what ob enforces (id style, path style) now, since renames are cheapest
while every path is changing anyway.

### 3. Modules

One branch per module repo, one commit for the CLI change. Keep the diff to
the CLI; the method's logic does not move. Run each module once by hand with
the new flags before wiring it into the plan.

### 4. Plan

Bump `api_version`, then `version:` (a new version makes `ob run` refuse an
out dir recorded under the old one, which keeps old and new results apart).
Apply the guide's plan changes. Repin every module to its migrated commit.

### 5. Slice the new plan

```bash
ob validate plan plan.yml                 # structure only
ob run plan.yml --dirty --dry --out-dir out_dry
grep '^# Stage' out_dry/Snakefile | sort | uniq -c    # nodes per stage
```

Compare nodes per stage with the old plan's dry run and explain every
difference. Then write a filter keeping the same datasets as the baseline,
run it, and commit the filter to the plan repo: it is the quick check for
everyone after you.

```bash
ob run plan.yml --dirty --filter slice.obfilter.yaml --out-dir out_new_slice --cores 8 -k
```

### 6. Prove nothing changed

```bash
python3 scripts/compare_trees.py out_old_slice out_new_slice \
    --rename-file OLD=NEW      # an output file renamed on purpose
    --rename-param OLD=NEW     # a parameter renamed on purpose
    --rename-module STAGE/OLD=NEW
    --ignore-module STAGE      # a stage whose modules were split or merged
```

It keys every scatter-node file by its lineage (stage, module, parameter
values per node), not by path, reads the nested (≤ 0.7) and flat (0.8)
layouts, and compares contents, decompressing `.gz`. It must print
`different: 0` and no file on one side only. Every rename flag is a claim
that the change was intended; list them in the migration's PR.

Gathers and collectors are skipped, since their outputs usually change shape.
Check them by hand: one row per expected member, no empty column, the report
renders and names every dataset, and each gather's `lineage.json` has the
member count you expect.

### 7. Publish

Push module branches, repin the plan to public URLs and commits, and rerun the
slice once from a fresh clone (`ob run` without `--dirty`).

## Restructuring is a separate step

Splitting a module, renaming parameters or changing what a stage outputs are
fine to do during a migration. They change node ids, so do them **before**
step 5, give `compare_trees.py` the matching renames, and keep them out of the
module CLI commits.

## Lessons that hold across versions

- `ob validate plan` checks structure. It does not fetch modules, so a key in
  the wrong place can pass validation and be ignored at run time. Only a
  dry run, then a real run, show that.
- **Labels come from lineage, never from paths.** Anything reading results
  (gather modules, reports, analyses) labels rows from `lineage.json` or the
  node's `parameters.json`. Code that parses directory names breaks at every
  layout change.
- A new consumer of an old file format finds quirks the old consumer
  tolerated (an R `write.table` header quoted as `"k=2"`). Check every column
  of a summary table, not just the numbers.
- Keep the old plan's worktree and its slice output until the new plan is
  published. They are the only reference for "same result".

## Adding a version

Write `references/to-<version>.md` with the same sections as `to-0.8.md`:
what changes (a table), conventions, modules (with the grep), plan, gathers if
affected, comparing (which flags the migration needs). Add a row to the table
above. If the output layout changes again, teach `compare_trees.py` the new
layout and keep the old ones: a migration always reads one tree of each.
