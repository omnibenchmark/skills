# Contributing

## Layout

```
.claude-plugin/
  marketplace.json   # registry; `source: "./"` points at this repo as one plugin
  plugin.json        # the plugin manifest
skills/
  <skill-name>/
    SKILL.md         # frontmatter (name, description) + instructions
    references/      # loaded on demand, not up-front
    scripts/         # executable helpers the agent shells out to
scripts/validate.py  # structural checks; run before every PR
```

## Rules

1. `name` in SKILL.md frontmatter must equal the directory name.
2. `description` is the only thing an agent sees before loading the skill. It must
   say *what it does* and *when to use it*, and name the concrete triggers
   (`omnibenchmark`, `ob validate`, "benchmark plan", ...). Keep it under 1024 chars.
3. Keep SKILL.md skimmable. Anything long or rarely needed goes in `references/`
   and is linked, not inlined — the agent loads it only when it needs it.
4. Prefer a deterministic script over prose whenever a step can fail silently.
5. The plugin `name` in a published marketplace entry is an immutable slug —
   renaming it breaks every existing install. Change `displayName` instead.
6. Bump `version` in `plugin.json` on every user-visible change.
