#!/usr/bin/env python3
"""Build extraction.json from the agent's tables, check it against the paper text,
then write the BEAD outputs.

    to_bead.py DIR [--no-quote-check]

DIR is the directory fetch_paper.py made. The agent writes tables/*.tsv into it
(columns in references/extraction-schema.md): paper, datasets, methods.
Writes next to them:

    extraction.json the tables as one document (derived; do not edit by hand)
    extraction.ttl  the same as RDF against bead-core (>= 0.2.0) / bead-software

and prints a markdown summary (paper, code, datasets) for the chat.

Checks, each an error unless noted:
  - required fields, known paper.type, unique ids
  - paper.type "method" iff some method has introduced_here: true
  - every entity's evidence.quote occurs in fulltext.md or a suppl/ text file
    (compared lowercased, letters and digits only, so hyphenation and quote
    styles do not matter); a dataset without a quote passes if each of its
    accession ids occurs there instead, and a method without a quote passes if
    its tool_url occurs there
  - warning: a dataset with neither accession nor URL; an accession whose id
    does not match its repository's pattern
Exit status: 0 clean (warnings allowed), 1 errors. Stdlib only.
"""
import argparse
import csv
import json
import pathlib
import re
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from fetch_paper import ACCESSIONS  # noqa: E402  same patterns the fetch step used

# bead-core >= 0.2.0; "other" stays a plain bead:Paper
PAPER_CLASS = {"method": "bead:MethodPaper", "benchmark": "bead:BenchmarkPaper",
               "resource": "bead:ResourcePaper", "other": "bead:Paper"}
PAPER_TYPES = set(PAPER_CLASS)
KINDS = ("datasets", "methods")
MAX_ROWS = 40  # datasets shown in the chat summary; the files hold all of them
PATTERNS = {repo: re.compile(rf"^(?:{pat})$") for repo, pat in ACCESSIONS}


def norm(s):
    return re.sub(r"[^a-z0-9]", "", s.lower())


def ttl_str(s):
    return '"' + str(s).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


TABLES = {  # file -> required columns; other columns are optional
    "datasets": ["id", "label"],
    "methods": ["id", "label", "role", "introduced_here"],
}


def split(cell):
    return [x.strip() for x in (cell or "").split(";") if x.strip()]


def read_tsv(path, required):
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    missing = [c for c in required if rows and c not in rows[0]]
    if missing:
        raise SystemExit(f"{path}: missing column(s) {missing}")
    return [{k: (v or "").strip() for k, v in r.items() if k} for r in rows]


def load_tables(d):
    """tables/*.tsv -> the extraction dict. Lists inside a cell are ';'-separated."""
    t = d / "tables"
    paper, gaps = {}, []
    for r in read_tsv(t / "paper.tsv", ["field", "value"]):
        if r["field"] == "gap":
            gaps.append(r["value"])
        else:
            paper[r["field"]] = r["value"]
    if paper.get("year", "").isdigit():
        paper["year"] = int(paper["year"])
    paper["evidence"] = {"quote": paper.pop("quote", "")}
    ex = {"paper": paper, "gaps": gaps}
    for name, required in TABLES.items():
        path = t / f"{name}.tsv"
        ex[name] = []
        for r in read_tsv(path, required) if path.exists() else []:
            e = {"id": r["id"], "label": r.get("label", ""), "evidence": {"quote": r.pop("quote", "")}}
            if name == "methods":
                e["role"] = r["role"]
                e["introduced_here"] = r["introduced_here"].lower() in ("true", "yes", "1")
                e["reference"] = r.get("reference", "")
                tool = {k: r[f"tool_{k}"] for k in ("kind", "url", "registry", "identifier", "version") if r.get(f"tool_{k}")}
                e["tools"] = [tool] if tool else []
            elif name == "datasets":
                e.update({k: r[k] for k in ("organism", "modality", "notes") if r.get(k)})
                e["accessions"] = [dict(zip(("repository", "id"), a.split(":", 1) if ":" in a else ("", a)))
                                   for a in split(r.get("accessions"))]
                e["urls"] = split(r.get("urls"))
            ex[name].append(e)
    return ex


def check(ex, corpus, quote_check):
    errors, warnings = [], []
    paper = ex.get("paper") or {}
    for k in ("doi", "title", "type"):
        if not paper.get(k):
            errors.append(f"paper.{k} missing")
    if paper.get("type") and paper["type"] not in PAPER_TYPES:
        errors.append(f"paper.type {paper['type']!r} not in {sorted(PAPER_TYPES)}")
    introduces = [m["id"] for m in ex.get("methods", []) if m.get("introduced_here")]
    if paper.get("type") == "method" and not introduces:
        errors.append("paper.type is 'method' but no method has introduced_here: true")
    if introduces and paper.get("type") != "method":
        errors.append(f"methods {introduces} are introduced_here but paper.type is {paper.get('type')!r}")

    ids = {}
    for kind in KINDS:
        for e in ex.get(kind, []):
            if not e.get("id"):
                errors.append(f"{kind}: entry without id: {e.get('label')!r}")
                continue
            if e["id"] in ids:
                errors.append(f"id {e['id']!r} used in both {ids[e['id']]} and {kind}")
            ids[e["id"]] = kind

    for d in ex.get("datasets", []):
        if not d.get("accessions") and not d.get("urls"):
            warnings.append(f"dataset {d['id']}: no accession or URL (list it under gaps if the paper gives none)")
        for acc in d.get("accessions", []):
            pat = PATTERNS.get(acc.get("repository"))
            if pat and not pat.match(acc.get("id", "")):
                warnings.append(f"dataset {d['id']}: {acc.get('id')!r} does not look like a {acc['repository']} id")

    if quote_check:
        entities = [("paper", paper)] + [(k, e) for k in KINDS for e in ex.get(k, [])]
        for kind, e in entities:
            q = (e.get("evidence") or {}).get("quote", "")
            label = e.get("id", "paper")
            if not q and kind == "datasets" and e.get("accessions"):
                for acc in e["accessions"]:
                    if norm(acc.get("id", "")) not in corpus:
                        errors.append(f"dataset {label}: accession {acc.get('id')!r} not found in the paper text")
            elif not q and kind == "methods" and any(t.get("url") for t in e.get("tools", [])):
                for t in e["tools"]:
                    if t.get("url") and norm(t["url"]) not in corpus:
                        errors.append(f"method {label}: tool_url {t['url']!r} not found in the paper text")
            elif not q:
                errors.append(f"{kind} {label}: no evidence.quote")
            elif norm(q) not in corpus:
                errors.append(f"{kind} {label}: quote not found in the paper text: {q[:80]!r}")
    return errors, warnings


def turtle(ex):
    p = ex["paper"]
    base = f"https://doi.org/{p['doi']}"
    iri = lambda i: f"<{base}#{i}>"  # noqa: E731
    out = [
        "@prefix bead: <https://purl.org/bead/> .",
        "@prefix dcterms: <http://purl.org/dc/terms/> .",
        "@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .",
        "@prefix schema: <http://schema.org/> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
        f"<{base}> a {PAPER_CLASS[p['type']]} ; dcterms:title {ttl_str(p['title'])}"
        + (f' ; dcterms:issued "{p["year"]}"^^xsd:gYear' if p.get("year") else "")
        + "".join(f" ;\n    bead:introduces {iri(m['id'])}" for m in ex.get("methods", []) if m.get("introduced_here"))
        + " .",
    ]
    for m in ex.get("methods", []):
        line = f"{iri(m['id'])} a bead:Method ; rdfs:label {ttl_str(m['label'])}"
        for n, tool in enumerate(m.get("tools", [])):
            tid = f"{m['id']}-tool{n}"
            line += f" ;\n    bead:implementedIn {iri(tid)}"
            cls = {"repository": "bead:Repository", "package": "bead:Package"}.get(tool.get("kind"), "schema:SoftwareApplication")
            t = f"{iri(tid)} a {cls}"
            if tool.get("url"):
                t += f" ; schema:url <{tool['url']}>"
            if tool.get("version"):
                t += f" ; bead:hasVersion {ttl_str(tool['version'])}"
            if tool.get("identifier"):
                t += f" ; bead:hasRegistryIdentifier {ttl_str(tool['identifier'])}"
            if tool.get("registry"):
                reg = "registry-" + norm(tool["registry"])
                t += f" ; bead:isAvailableFrom {iri(reg)}"
                out.append(f"{iri(reg)} a bead:SoftwareRegistry ; rdfs:label {ttl_str(tool['registry'])} .")
            out.append(t + " .")
        out.append(line + " .")
    for d in ex.get("datasets", []):
        line = f"{iri(d['id'])} a bead:Dataset ; rdfs:label {ttl_str(d['label'])}"
        for a in d.get("accessions", []):
            line += f" ;\n    dcterms:identifier {ttl_str(a['repository'] + ':' + a['id'])}"
        for u in d.get("urls", []):
            line += f" ;\n    schema:url <{u}>"
        out.append(line + " .")
    return "\n".join(out) + "\n"


def markdown(ex):
    p = ex["paper"]
    out = [f"**{p['title']}** ({p.get('year', '')}) doi:{p['doi']}",
           f"Type: **{p['type']}**: {p.get('type_rationale', '')}", "",
           "| method | role | code |", "|---|---|---|"]
    for m in ex.get("methods", []):
        code = [t.get("url") or f"{t.get('registry', '')}:{t.get('identifier', '')}" for t in m.get("tools", [])]
        out.append(f"| {m['label']} | {m['role']} | {', '.join(code) or '**none given**'} |")
    out += ["", "| dataset | accessions / urls |", "|---|---|"]
    datasets = ex.get("datasets", [])
    for d in datasets[:MAX_ROWS]:
        where = [f"{a['repository']}:{a['id']}" for a in d.get("accessions", [])] + d.get("urls", [])
        out.append(f"| {d['label']} | {', '.join(where) or '**none given**'} |")
    if len(datasets) > MAX_ROWS:
        out.append(f"| ... {len(datasets) - MAX_ROWS} more in tables/datasets.tsv | |")
    if ex.get("gaps"):
        out += ["", "Gaps:"] + [f"- {g}" for g in ex["gaps"]]
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("dir", type=pathlib.Path)
    ap.add_argument("--no-quote-check", action="store_true", help="skip the verbatim-evidence check")
    a = ap.parse_args()

    ex = load_tables(a.dir)
    (a.dir / "extraction.json").write_text(json.dumps(ex, indent=1))
    suppl = sorted(p for p in (a.dir / "suppl").glob("*") if p.suffix in (".tsv", ".txt", ".csv")) if (a.dir / "suppl").exists() else []
    texts = [a.dir / "fulltext.md"] + suppl
    corpus = "".join(norm(t.read_text(errors="replace")) for t in texts if t.exists())

    errors, warnings = check(ex, corpus, not a.no_quote_check)
    for w in warnings:
        print(f"WARN  {w}", file=sys.stderr)
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)
    if errors:
        print(f"{len(errors)} error(s); fix extraction.json and rerun", file=sys.stderr)
        return 1

    (a.dir / "extraction.ttl").write_text(turtle(ex))
    print(markdown(ex))
    print(f"\nwrote {a.dir}/extraction.json, {a.dir}/extraction.ttl", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
