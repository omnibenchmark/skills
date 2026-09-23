# Omnibenchmark agent skills

Agent skills that help a coding agent (Claude Code and compatible clients) work with
[Omnibenchmark](https://omnibenchmark.org) — the `ob` CLI for declarative, reproducible
benchmarks. They cover authoring benchmark plans, scaffolding and packaging modules,
wrapping upstream tools to satisfy a plan stage, and validating the result.

## Install (Claude Code)

```
/plugin marketplace add omnibenchmark/skills
/plugin install omnibenchmark@omnibenchmark
```

## Install (any agent)

Copy a skill directory into your agent's skills path:

```
cp -r skills/omnibenchmark-module ~/.claude/skills/
```

## Skills

| Skill | What it does |
| --- | --- |
| `omnibenchmark-cli` | Resolves `ob` commands against the installed binary rather than from memory |
| `omnibenchmark-plan` | Authors and migrates benchmark plans at `api_version` 0.7.0 |
| `omnibenchmark-module` | Takes `ob create module` output to a module that runs under a plan |
| `omnibenchmark-packaging` | pixi environments, dependency bumps, conda export |
| `omnibenchmark-wrapping` | Wraps an upstream Python/R package or repo to satisfy a stage |
| `omnibenchmark-validate` | Plan and module validation, stage validators, CI |

## Versions

These skills target `ob` 0.7 and `api_version: "0.7.0"`. The CLI reference in
`skills/omnibenchmark-cli/references/cli.md` is generated from a real binary and
version-stamped; regenerate it with
`python skills/omnibenchmark-cli/scripts/refresh_cli_reference.py`.

## Development

```
python scripts/validate.py
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ROADMAP.md](docs/ROADMAP.md).
