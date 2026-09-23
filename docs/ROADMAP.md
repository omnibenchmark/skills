# Roadmap and unresolved questions

## Deferred features

- **Apptainer / Docker software backend.** `ob` supports it; these skills cover pixi and
  conda only. A future `omnibenchmark-containers` skill would cover image builds, pinning
  and the `software_backend: apptainer` path.
- **Telemetry MCP.** The Aspire dashboard exposes a service consuming `ob` telemetry.
  Once it is reachable from an agent, a skill for reading run telemetry (failures,
  runtimes, resource use) would pair naturally with `omnibenchmark-validate`.
- **`ob dashboard` and `ob archive`.** Present in the CLI, not yet covered by any skill.
- **`ob remote` / storage.** S3 and MinIO versioning is documented in design 003 (Draft)
  and has no skill.

## Unresolved design questions

These came out of authoring and need a decision from the benchmark maintainers. Each one
changes what the skills tell a module author to do, so they are worth settling before the
next batch of ports.

### 1. The `--name` contract — highest impact

At `api_version <= 0.4.0` the Snakemake backend passes the **dataset id** as `--name`, as
an explicitly commented workaround slated for removal. From 0.5.0 it passes the **module's
own id**. Every current omni-scrna module writes `<name>_<suffix>` against a plan template
declaring `{dataset}_<suffix>`, so those modules write a filename the plan does not declare
once the workaround goes. `ob validate plan` cannot detect this.

Options: (a) plans declare `{name}_...` templates; (b) modules parse the dataset out of
`--output_dir`; (c) wait for a new reserved parameter carrying the dataset. Until this is
settled both the module and wrapping skills tell the author to agree it with the plan
author rather than assuming.

### 2. Stage id naming

`docs/stage-schemas.md` in the plan repo uses `two-filter` / `five-pca` /
`six-embedding-metrics`; the live plan and `schema/*.json` use `FILT` / `PCA` / `EMBED-M`;
`validators/` contains both styles. Which is canonical?

### 3. `--strict` in CI

Replacing the scaffold's single `default` entrypoint with named ones triggers
"omnibenchmark.yaml 'entrypoints' is missing required 'default' key", and
`ob validate module --strict` exits 1. Measured on `scanpy`, `5-pca-irlba-r` and `metrics`:
plain exit 0, strict exit 1 for all three. So `--strict` cannot currently be enabled in CI
for any production module. Either keep a `default` alias, or change the check upstream.

### 4. Environment drift between modules and the plan

A module exports `envs/<name>.yml` with pixi; the plan repo keeps its own copy. They have
drifted — `split-stages-plan/envs/scanpy.yml` carries the pixi do-not-edit banner yet
differs from the `scanpy` module's export (`python-igraph >=1.0.0,<2` vs `>=0.11,<1`,
`leidenalg >=0.11.0,<0.12` vs `>=0.10,<1`, an extra channel, `obkit` moved out of the
`pip:` block). Only 6 of the plan's 18 env files carry the banner. Is "diff and copy by
hand" the intended process, or should a bot own it?

### 5. `metric_collectors:`

Still a model field; design 010 calls it a global gather that should eventually be
deprecated. The skills currently present `gather` at 0.7.0 as the preferred route and
`metric_collectors` as legacy. Confirm or correct.

### 6. New-module bootstrap order

A plan pins a module by `repository.{url, commit}`, but the commit does not exist until
the module is pushed. Should the skills teach push-then-pin-then-PR, or is a branch or tag
pin acceptable while an arm is under review?

## Upstream issues worth filing

Found while authoring; all verified against the `gather-lean-3` checkout.

1. The module scaffold emits `env/.gitkeep` but its own `.gitignore` lists `env/`, so the
   directory it creates can never be committed. Production modules use `envs/` anyway.
2. The model's "Found duplicate module ids" check can never fire — `get_modules()` returns
   a dict keyed by id, so duplicates collapse before the check runs. The analogous
   output-id case is deliberate and documented; this one looks accidental.
3. Design 004 s3.10 presents `requires_capabilities` as requiring api >= 0.7.0, but the
   model does not gate it (nor `Module.requires`). A 0.4.0 plan using it parses fine, and
   `benchmark_pcaacc.yaml` does exactly that.
4. Design 004 s3.1 contradicts itself on the `api_version` default ("0.4" in one place,
   "0.3" in another); the model default is `0.4.0`.
5. Design 007 s3 documents output nesting as `<stage>/<module>/.<hash>/` while 004 s3.7
   still shows `<stage_id>/<wildcard_pattern>/<params_hash>/`. The generated Snakefile
   matches 007.
6. `Resources` in the model has a `gpu` field that 004 s7.2 does not list.
7. `omni-scrna/boilerplate` `AGENTS.md` documents the module manifest key as
   `boilerplate: {repo, ref, lang}`, but its own `scripts/pull.py` reads `templates:` and
   every real module uses `templates:`. The doc is stale.
8. `metrics/omnibenchmark.yaml` declares `templates:` twice, so YAML silently keeps the
   second.
9. The plan repo's validators print OK/FAIL but exit 0 regardless, so CI use needs a grep
   on output rather than the exit status.
