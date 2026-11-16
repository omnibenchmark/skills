#!/usr/bin/env python3
"""Compare the outputs of a benchmark before and after an api migration.

    compare_trees.py OLD_OUT NEW_OUT [--rename-file OLD=NEW]... \
        [--rename-param OLD=NEW]... [--rename-module STAGE/OLD=NEW]... \
        [--ignore-module STAGE]...

Every output file of a scatter node is keyed by its lineage: for each node from
the root down, (stage, module, parameter values from parameters.json), plus the
file name. Paths are never compared. Each tree's layout is detected: nested
(stage/module/.hash, api <= 0.7) or flat (stage.module.hash, api 0.8), so any
pair lines up. Gzipped files are compared
decompressed. Gather and collector directories are skipped: their outputs
change shape in the migration and are checked separately.

Renames say what the migration changed on purpose: an output file name, a
parameter name, a module id. They are written old=new and applied to OLD_OUT. --ignore-module drops the module id of a stage
from the key, for a stage whose modules were split or merged (the parameters
still tell its nodes apart).

Exit 0 when every file matches, 1 otherwise.
"""

import argparse
import gzip
import json
import sys
from pathlib import Path

SKIP_FILES = {"parameters.json", "lineage.json", "manifest.json", "Snakefile",
              "performance.txt", "performances.tsv"}
SKIP_DIRS = {"by-params"}  # the 0.8.0 view of readable names, made of links


def params_of(node_dir):
    f = node_dir / "parameters.json"
    return json.loads(f.read_text()) if f.is_file() else {}


def nested_nodes(rel):
    """data/D1/.abc/methods/M1/.def/x.txt -> [(data, D1, dir), ...], file name.
    A segment that does not follow the stage/module/.param triple (a collector
    directory, a .default-less layout) makes the file unkeyable: None."""
    parts = rel.parts[:-1]
    if len(parts) % 3:
        return None
    triples = [parts[i:i + 3] for i in range(0, len(parts), 3)]
    if not all(p.startswith(".") for _, _, p in triples):
        return None
    return [(s, m, Path(*parts[:i * 3 + 3])) for i, (s, m, _) in enumerate(triples)]


def flat_nodes(rel):
    """data.D1.abc/methods.M1.def/x.txt -> [(data, D1, dir), ...]. A join or
    gather segment carries a member digest (`-<hash>`), cut off here; the caller
    drops gathers by the `kind` in their lineage.json."""
    out = []
    for i, seg in enumerate(rel.parts[:-1]):
        fields = seg.split("-", 1)[0].split(".")
        if len(fields) < 2:
            return None
        out.append((fields[0], fields[1], Path(*rel.parts[:i + 1])))
    return out


def is_flat(root):
    """Flat when a top-level node directory is `stage.module…`; a nested tree
    starts with bare stage directories."""
    dirs = [d.name for d in root.iterdir()
            if d.is_dir() and not d.name.startswith(".") and d.name not in SKIP_DIRS]
    return any("." in d for d in dirs)


def is_gather(node_dir):
    f = node_dir / "lineage.json"
    return f.is_file() and json.loads(f.read_text()).get("kind") in ("gather", "collector")


def read(path):
    data = path.read_bytes()
    return gzip.decompress(data) if path.suffix == ".gz" else data


def tree(root, renames):
    flat = is_flat(root)
    files, unkeyed = {}, []
    for path in sorted(root.rglob("*")):
        rel = path.relative_to(root)
        if (not path.is_file() or path.is_symlink() or path.name in SKIP_FILES
                or path.name.endswith("_performance.txt")
                or rel.parts[0].startswith(".")  # .snakemake, .logs, .modules, ...
                or SKIP_DIRS & set(rel.parts)):
            continue
        nodes = (flat_nodes if flat else nested_nodes)(rel)
        if not nodes:
            unkeyed.append(rel)
            continue
        if any(is_gather(root / d) for _, _, d in nodes):
            continue
        key = []
        for stage, module, d in nodes:
            module = renames["module"].get(f"{stage}/{module}", module)
            if stage in renames["ignore"]:
                module = "*"
            params = {renames["param"].get(k, k): v for k, v in params_of(root / d).items()}
            key.append((stage, module, json.dumps(params, sort_keys=True)))
        name = renames["file"].get(path.name, path.name)
        key = (tuple(key), name)
        if key in files:
            sys.exit(f"two files share the key {key}: {files[key]} and {path}")
        files[key] = path
    return files, unkeyed


def pairs(values):
    return dict(v.split("=", 1) for v in values)


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("old", type=Path)
    p.add_argument("new", type=Path)
    p.add_argument("--rename-file", action="append", default=[])
    p.add_argument("--rename-param", action="append", default=[])
    p.add_argument("--rename-module", action="append", default=[])
    p.add_argument("--ignore-module", action="append", default=[])
    a = p.parse_args()
    renames = {"file": pairs(a.rename_file), "param": pairs(a.rename_param),
               "module": pairs(a.rename_module), "ignore": set(a.ignore_module)}

    old, old_unkeyed = tree(a.old, renames)
    new, new_unkeyed = tree(a.new, {**renames, "file": {}, "param": {}, "module": {}})
    only_old, only_new = sorted(old.keys() - new.keys()), sorted(new.keys() - old.keys())
    differ = sorted(k for k in old.keys() & new.keys() if read(old[k]) != read(new[k]))

    print(f"old: {len(old)} files, new: {len(new)} files")
    print(f"only in old: {len(only_old)}, only in new: {len(only_new)}, different: {len(differ)}")
    for label, keys, side in (("only in old", only_old, old), ("only in new", only_new, new),
                              ("different", differ, new)):
        for k in keys[:10]:
            print(f"  {label}: {side[k]}")
    for label, paths in (("old", old_unkeyed), ("new", new_unkeyed)):
        if paths:
            print(f"  {len(paths)} {label} files outside any node, not compared, e.g. {paths[0]}")
    sys.exit(1 if only_old or only_new or differ or not old else 0)


if __name__ == "__main__":
    main()
