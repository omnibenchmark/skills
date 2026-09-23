#!/usr/bin/env python3
"""Structural checks for the skills repo. Exit 1 on any failure."""
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
MAX_DESCRIPTION = 1024
errors = []


def parse_frontmatter(text):
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 3)
    if end == -1:
        return None
    out = {}
    for line in text[4:end].splitlines():
        if ":" in line and not line.startswith((" ", "\t", "#")):
            k, v = line.split(":", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


LEAK_PATTERNS = [
    (re.compile(r"/(?:home|Users)/[A-Za-z0-9._-]+/"), "absolute path into someone's home directory"),
    (re.compile(r"[A-Za-z0-9._%+-]+@(?!example\.(?:com|org))[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "email address"),
]
LEAK_SUFFIXES = {".md", ".py", ".R", ".sh", ".toml", ".yaml", ".yml", ".json", ".txt"}


def check_no_leaks(skills_root):
    """Published skills must cite public repo paths, never local or personal ones."""
    for path in sorted(skills_root.rglob("*")):
        if not path.is_file() or path.suffix not in LEAK_SUFFIXES:
            continue
        try:
            text = path.read_text()
        except UnicodeDecodeError:
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for pattern, label in LEAK_PATTERNS:
                m = pattern.search(line)
                if m:
                    rel = path.relative_to(skills_root.parent)
                    errors.append(f"{rel}:{lineno}: {label} ({m.group(0)!r}) — cite the public repo path instead")


def main():
    marketplace = json.loads((ROOT / ".claude-plugin" / "marketplace.json").read_text())
    plugin = json.loads((ROOT / ".claude-plugin" / "plugin.json").read_text())

    names = [p["name"] for p in marketplace["plugins"]]
    if plugin["name"] not in names:
        errors.append(f"plugin.json name {plugin['name']!r} not in marketplace.json {names}")
    for entry in marketplace["plugins"]:
        src = (ROOT / entry["source"]).resolve()
        if not src.is_dir():
            errors.append(f"marketplace entry {entry['name']!r}: source {entry['source']} missing")

    skill_dirs = sorted(d for d in (ROOT / "skills").iterdir() if d.is_dir())
    if not skill_dirs:
        errors.append("no skills found under skills/")
    for d in skill_dirs:
        md = d / "SKILL.md"
        if not md.exists():
            errors.append(f"{d.name}: no SKILL.md")
            continue
        fm = parse_frontmatter(md.read_text())
        if fm is None:
            errors.append(f"{d.name}: SKILL.md has no YAML frontmatter")
            continue
        if fm.get("name") != d.name:
            errors.append(f"{d.name}: frontmatter name {fm.get('name')!r} != directory name")
        desc = fm.get("description", "")
        if not desc:
            errors.append(f"{d.name}: frontmatter has no description")
        elif len(desc) > MAX_DESCRIPTION:
            errors.append(f"{d.name}: description is {len(desc)} chars (max {MAX_DESCRIPTION})")

    check_no_leaks(ROOT / "skills")

    print(f"checked {len(skill_dirs)} skill(s): {', '.join(d.name for d in skill_dirs)}")
    for e in errors:
        print(f"FAIL {e}", file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
