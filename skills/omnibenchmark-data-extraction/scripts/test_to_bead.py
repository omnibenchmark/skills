#!/usr/bin/env python3
"""Smoke test for to_bead.py: clean tables pass, a paraphrased quote or a bad type fails."""
import pathlib
import subprocess
import sys
import tempfile

HERE = pathlib.Path(__file__).resolve().parent
TEXT = ("We present FooTool, a method for cell clus-\ntering. It is compared against Bar on PBMC data "
        "(GSE12345) using the adjusted Rand index. Figure 2 shows ARI.")
TABLES = {
    "paper": "field\tvalue\ndoi\t10.1/x\ntitle\tT\nyear\t2024\ntype\tmethod\nquote\tWe present FooTool, a method\ngap\tno code link for Bar\n",
    "tasks": "id\tlabel\tquote\nclust\tclustering\tcell clustering\n",
    "methods": ("id\tlabel\trole\tintroduced_here\ttool_kind\ttool_registry\ttool_identifier\tquote\n"
                "foo\tFooTool\tproposed\ttrue\tpackage\tPyPI\tfootool\tWe present FooTool\n"
                "bar\tBar\tcompared\tfalse\t\t\t\tcompared against Bar\n"),
    "datasets": "id\tlabel\taccessions\turls\nidx\tPBMC\tGEO:GSE12345\t\n",  # no quote: the accession is checked
    "metrics": "id\tlabel\thigher_is_better\tquote\nari\tARI\ttrue\tadjusted Rand index\n",
    "comparisons": "id\ttask\tdatasets\tmethods\tmetrics\tartifacts\tquote\nc1\tclust\t*\tfoo;bar\tari\tFig. 2\tFigure 2 shows ARI\n",
}


def run(tables):
    d = pathlib.Path(tempfile.mkdtemp())
    (d / "fulltext.md").write_text(TEXT)
    (d / "tables").mkdir()
    for name, body in tables.items():
        (d / "tables" / f"{name}.tsv").write_text(body)
    return subprocess.run([sys.executable, str(HERE / "to_bead.py"), str(d)], capture_output=True, text=True), d


r, d = run(TABLES)
assert r.returncode == 0, r.stderr
assert len((d / "table.tsv").read_text().splitlines()) == 3  # header + foo, bar on the one dataset
ttl = (d / "extraction.ttl").read_text()
assert "a bead:MethodPaper" in ttl and "bead:introduces" in ttl and "bead:reports" in ttl
assert (d / "extraction.json").exists()

bad = dict(TABLES)
bad["datasets"] = "id\tlabel\taccessions\tquote\nidx\tPBMC\tGEO:GSE99999\t\n"
bad["metrics"] = "id\tlabel\tquote\nari\tARI\tthe Rand index, adjusted\n"
bad["methods"] = TABLES["methods"].replace("proposed\ttrue", "proposed\tfalse")
r, _ = run(bad)
for msg in ("GSE99999", "quote not found", "no method has introduced_here"):
    assert r.returncode == 1 and msg in r.stderr, (msg, r.stderr)
print("ok")
