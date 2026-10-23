#!/usr/bin/env python3
"""Fetch a paper by DOI and lay it out as plain text the agent can extract from.

    fetch_paper.py DOI [--out DIR] [--file PATH] [--no-suppl]

Writes into DIR (default: ./extractions/<doi-slug>/):

    meta.json        OpenAlex metadata + where the text came from (`source`)
    fulltext.md      the paper as markdown: abstract, sections, figure and table
                     captions, tables, data/code availability, supplementary
                     material, references. Evidence quotes are checked against it.
    candidates.json  every accession number and URL found, with its section
    suppl/           supplementary files; .xlsx -> .tsv, .docx/.pdf -> .txt

Text sources, first that works: --file, Europe PMC JATS,
NCBI PMC JATS, bioRxiv/medRxiv JATS, the open-access PDF from OpenAlex,
then abstract only. Supplements: Europe PMC's bundle, else links on the
publisher's landing page.
Exit status: 0 full text, 3 abstract only (ask the user for the file), 1 error.

Set OPENALEX_MAILTO to join OpenAlex's polite pool. Stdlib only, plus
`pdftotext` (poppler) for PDFs.
"""
import argparse
import io
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

UA = "omnibenchmark-data-extraction/0.1 (+https://github.com/omnibenchmark/skills)"
XLINK = "{http://www.w3.org/1999/xlink}href"
KEEP = (".xlsx", ".csv", ".tsv", ".txt", ".docx", ".pdf")  # tables and documents; skips figures, code, binaries

# (repository, pattern). Order matters only for readability.
ACCESSIONS = [
    ("GEO", r"\bG(?:SE|DS)\d{3,}\b"),
    ("SRA/ENA", r"\b(?:PRJ(?:NA|EB|DB)|[SED]R[PRXS])\d{5,}\b"),
    ("ArrayExpress/BioStudies", r"\bE-[A-Z]{4}-\d+\b|\bS-[A-Z]{2,5}\d+\b"),
    ("EGA", r"\bEGA[SDC]\d{11}\b"),
    ("dbGaP", r"\bphs\d{6}(?:\.v\d+\.p\d+)?\b"),
    ("PRIDE", r"\bPXD\d{6}\b"),
    ("Synapse", r"\bsyn\d{6,}\b"),
    ("Zenodo", r"\b10\.5281/zenodo\.\d+\b"),
    ("Figshare", r"\b10\.6084/m9\.figshare\.[\d.v]+\b"),
    ("Dryad", r"\b10\.5061/dryad\.[a-z0-9]+\b"),
]
URL = re.compile(r"https?://[^\s<>\"')\]]+")
URL_KIND = [
    ("code", ("github.com", "gitlab", "bitbucket.org", "bioconductor.org", "cran.r-project.org",
              "pypi.org", "anaconda.org", "bioconda", "crates.io", "hub.docker.com", "codeocean")),
    ("data", ("ncbi.nlm.nih.gov/geo", "ebi.ac.uk", "zenodo.org", "figshare", "datadryad", "cellxgene",
              "humancellatlas", "data.humancellatlas", "synapse.org", "osf.io", "10xgenomics.com",
              "singlecell.broadinstitute.org", "openproblems", "kaggle.com", "mendeley.com", "ega-archive")),
]


def get(url, binary=False):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            data = r.read()
    except urllib.error.HTTPError as e:
        if e.code < 500:
            raise
        with urllib.request.urlopen(req, timeout=60) as r:  # Europe PMC 500s are often transient
            data = r.read()
    return data if binary else data.decode("utf-8", "replace")


def get_json(url):
    try:
        return json.loads(get(url))
    except Exception as e:  # network or 404: the caller falls through to the next source
        print(f"  ({url}: {e})", file=sys.stderr)
        return None


def openalex(doi):
    q = urllib.parse.quote(f"doi:{doi}")
    mailto = os.environ.get("OPENALEX_MAILTO")
    url = f"https://api.openalex.org/works/{q}" + (f"?mailto={urllib.parse.quote(mailto)}" if mailto else "")
    w = get_json(url) or {}
    inv = w.get("abstract_inverted_index") or {}
    words = sorted((i, word) for word, idx in inv.items() for i in idx)
    oa = w.get("open_access") or {}
    best = w.get("best_oa_location") or {}
    return {
        "doi": doi,
        "openalex_id": w.get("id"),
        "title": w.get("title"),
        "year": w.get("publication_year"),
        "openalex_type": w.get("type"),
        "venue": ((w.get("primary_location") or {}).get("source") or {}).get("display_name"),
        "is_oa": oa.get("is_oa"),
        "oa_status": oa.get("oa_status"),
        "license": best.get("license"),
        "pdf_url": best.get("pdf_url"),
        "landing_page_url": best.get("landing_page_url") or f"https://doi.org/{doi}",
        "abstract": " ".join(word for _, word in words) or None,
    }


def europepmc_pmcid(doi):
    q = urllib.parse.quote(f'DOI:"{doi}"')
    r = get_json(f"https://www.ebi.ac.uk/europepmc/webservices/rest/search?query={q}&format=json&resultType=core")
    for hit in ((r or {}).get("resultList") or {}).get("result", []):
        if hit.get("pmcid"):  # not only inEPMC: NCBI may hold the text when Europe PMC does not
            return hit["pmcid"]
    return None


# ---------------------------------------------------------------- JATS -> markdown

def text(el):
    return re.sub(r"\s+", " ", "".join(el.itertext())).strip()


def jats_table(tw, out):
    label = text(tw.find("label")) if tw.find("label") is not None else "Table"
    cap = tw.find("caption")
    out.append(f"\n**{label}.** {text(cap) if cap is not None else ''}\n")
    for tr in tw.iter("tr"):
        out.append("| " + " | ".join(text(c) for c in tr if c.tag in ("td", "th")) + " |")
    for fn in tw.iter("table-wrap-foot"):
        out.append(text(fn))
    out.append("")


def jats_walk(el, out, depth):
    for child in el:
        tag = child.tag
        if tag in ("sec", "app", "notes", "ack", "boxed-text"):
            title = child.find("title")
            heading = text(title) if title is not None else child.get("notes-type") or child.get("sec-type") or ""
            if heading:
                out.append(f"\n{'#' * min(depth, 6)} {heading}\n")
            jats_walk(child, out, depth + 1)
        elif tag == "p":
            out.append(text(child) + "\n")
        elif tag in ("list",):
            out.extend(f"- {text(li)}" for li in child.iter("list-item"))
            out.append("")
        elif tag == "fig":
            label = child.find("label")
            cap = child.find("caption")
            out.append(f"\n**{text(label) if label is not None else 'Figure'}.** {text(cap) if cap is not None else ''}\n")
        elif tag == "table-wrap":
            jats_table(child, out)
        elif tag == "supplementary-material":
            label = child.find("label")
            cap = child.find("caption")
            href = child.get(XLINK) or next((m.get(XLINK) for m in child.iter("media") if m.get(XLINK)), "")
            out.append(f"- **{text(label) if label is not None else 'Supplement'}** {text(cap) if cap is not None else ''} [{href}]")
        elif tag in ("title", "label", "ref-list", "fn-group"):
            continue
        else:
            jats_walk(child, out, depth)


def jats_refs(root, out):
    refs = root.findall(".//ref-list/ref")
    if not refs:
        return
    out.append("\n## References\n")
    for ref in refs:
        cit = next(iter(ref.findall(".//element-citation") + ref.findall(".//mixed-citation")), None)
        if cit is None:
            continue
        title = cit.find("article-title")
        doi = cit.find("pub-id[@pub-id-type='doi']")
        label = ref.find("label")
        out.append(f"- [{text(label) if label is not None else ref.get('id', '')}] "
                   f"{text(title) if title is not None else text(cit)[:200]}"
                   f"{' doi:' + text(doi) if doi is not None else ''}")


def jats_to_md(xml):
    # DOCTYPE lines reference DTDs ElementTree cannot fetch; drop them.
    root = ET.fromstring(re.sub(r"<!DOCTYPE[^>]*>", "", xml, count=1).encode())
    for el in root.iter():  # strip namespaces other than xlink, which we read explicitly
        if isinstance(el.tag, str) and el.tag.startswith("{") and "xlink" not in el.tag:
            el.tag = el.tag.split("}", 1)[1]
    if root.tag != "article":  # NCBI efetch wraps it in <pmc-articleset>
        root = root.find(".//article") if root.find(".//article") is not None else root
    for x in root.iter("xref"):  # citations as [52], so they don't glue onto accessions
        if x.get("ref-type") == "bibr":
            x.text, x[:] = f"[{''.join(x.itertext())}]", []
    out = []
    title = root.find(".//article-meta//article-title")
    out.append(f"# {text(title) if title is not None else ''}\n")
    for ab in root.findall(".//article-meta/abstract"):
        out.append("\n## Abstract\n")
        jats_walk(ab, out, 3)
    for notes in root.findall(".//front//notes"):  # some journals put data availability here
        jats_walk(_wrap(notes), out, 2)
    for part in ("body", "back", "floats-group"):
        node = root.find(part)
        if node is not None:
            jats_walk(node, out, 2)
    jats_refs(root, out)
    return "\n".join(out)


def _wrap(el):
    w = ET.Element("wrap")
    w.append(el)
    return w


# ---------------------------------------------------------------- other formats

def pdf_to_text(path):
    if not shutil.which("pdftotext"):
        raise SystemExit("pdftotext not found; install poppler, or read the PDF directly and save it as fulltext.md")
    return subprocess.run(["pdftotext", "-enc", "UTF-8", str(path), "-"], capture_output=True, text=True, check=True).stdout


def xlsx_to_tsv(path):
    """Each sheet of an .xlsx as TSV text, in sheet order. Stdlib only."""
    ns = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    with zipfile.ZipFile(path) as z:
        shared = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).findall("m:si", ns):
                shared.append("".join(t.text or "" for t in si.iter(f"{{{ns['m']}}}t")))
        blocks = []
        sheets = [n for n in z.namelist() if re.match(r"xl/worksheets/sheet\d+\.xml$", n)]
        for name in sorted(sheets, key=lambda n: int(re.search(r"(\d+)\.xml$", n).group(1))):
            rows = []
            for row in ET.fromstring(z.read(name)).iter(f"{{{ns['m']}}}row"):
                cells = []
                for c in row.findall("m:c", ns):
                    col = 0  # empty cells are omitted, so place each by its reference (e.g. "C7")
                    for ch in re.match(r"[A-Z]*", c.get("r", "")).group(0):
                        col = col * 26 + ord(ch) - 64
                    cells.extend([""] * max(0, col - 1 - len(cells)))
                    v = c.find("m:v", ns)
                    val = v.text if v is not None else "".join(t.text or "" for t in c.iter(f"{{{ns['m']}}}t"))
                    if c.get("t") == "s" and val:
                        val = shared[int(val)]
                    cells.append((val or "").replace("\t", " ").replace("\n", " "))
                rows.append("\t".join(cells))
            blocks.append("\n".join(rows) + "\n")
    return blocks


def local_file(path):
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        return pdf_to_text(path), "local-pdf"
    raw = path.read_text(errors="replace")
    if suffix in (".xml", ".nxml") or raw.lstrip().startswith("<?xml"):
        return jats_to_md(raw), "local-jats"
    if suffix in (".html", ".htm"):
        raw = re.sub(r"(?is)<(script|style).*?</\1>", "", raw)
        raw = re.sub(r"(?i)<(h[1-6])[^>]*>", "\n## ", raw)
        raw = re.sub(r"(?i)<(p|br|li|tr)[^>]*>", "\n", raw)
        return re.sub(r"[ \t]+", " ", re.sub(r"<[^>]+>", "", raw)), "local-html"
    return raw, "local-text"


def store_suppl(dest, name, data, made, depth=0):
    """Save one supplementary file into dest, unpacking zips and converting tables to text."""
    name = pathlib.PurePath(name).name  # flatten; never trust archive paths
    if name.lower().endswith(".zip") and depth < 3:  # journals often zip their own zip
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for info in z.infolist():
                if not info.is_dir():
                    store_suppl(dest, info.filename, z.read(info), made, depth + 1)
        return
    if not name.lower().endswith(KEEP):
        return
    dest.mkdir(exist_ok=True)
    target = dest / name
    target.write_bytes(data)
    made.append(name)
    try:
        suffix = target.suffix.lower()
        if suffix == ".xlsx":
            for n, sheet in enumerate(xlsx_to_tsv(target)):  # name.tsv, name.sheet2.tsv, ...
                target.with_suffix(".tsv" if n == 0 else f".sheet{n + 1}.tsv").write_text(sheet)
        elif suffix == ".docx":
            target.with_suffix(".txt").write_text(docx_to_text(target))
        elif suffix == ".pdf":
            target.with_suffix(".txt").write_text(pdf_to_text(target))
    except Exception as e:  # a broken supplement should not sink the paper
        print(f"  (could not convert {name}: {e})", file=sys.stderr)


def fetch_suppl(doi, pmcid, out):
    """Europe PMC's bundle first, then links scraped from the publisher's landing page."""
    made = []
    if pmcid:
        try:
            blob = get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/supplementaryFiles", binary=True)
            store_suppl(out / "suppl", "bundle.zip", blob, made)
        except Exception as e:
            print(f"  (no Europe PMC supplementary bundle: {e})", file=sys.stderr)
    if made:
        return made
    # ponytail: regex over the landing page, not a per-publisher scraper. Covers Springer
    # Nature (MOESM), Cell/Elsevier (mmc), OUP/Wiley/bioRxiv (supp, media-N); sites behind
    # a bot wall return nothing, and the skill then asks the user for the files.
    try:
        html = get(f"https://doi.org/{doi}")
    except Exception as e:
        print(f"  (publisher page unreachable: {e})", file=sys.stderr)
        return made
    links = set(re.findall(r"""(?:href|src)=["']([^"']+\.(?:xlsx?|csv|tsv|txt|docx?|pdf|zip)(?:\?[^"']*)?)["']""", html, re.I))
    links = sorted(urllib.parse.urljoin(f"https://doi.org/{doi}", u.replace("&amp;", "&")) for u in links
                   if re.search(r"suppl|moesm|mmc\d|/esm/|media-\d|supp", u, re.I))
    for url in links[:40]:
        try:
            name = urllib.parse.unquote(urllib.parse.urlparse(url).path.rsplit("/", 1)[-1])
            store_suppl(out / "suppl", name, get(url, binary=True), made)
            print(f"  publisher supplement: {name}", file=sys.stderr)
        except Exception as e:
            print(f"  (could not fetch {url}: {e})", file=sys.stderr)
    return made


def docx_to_text(path):
    w = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read("word/document.xml"))
    return "\n".join("".join(t.text or "" for t in p.iter(f"{w}t")) for p in root.iter(f"{w}p"))


# ---------------------------------------------------------------- candidates

def candidates(md):
    found, section = {}, ""
    for line in md.splitlines():
        if line.startswith("#"):
            section = line.lstrip("# ").strip()
            continue
        if section == "References":
            continue  # cited papers' links are not this paper's data
        for repo, pat in ACCESSIONS:
            for m in re.finditer(pat, line):
                found.setdefault(("accession", repo, m.group(0)), set()).add(section)
        for m in URL.finditer(line):
            url = m.group(0).rstrip(".,;:")
            kind = next((k for k, hosts in URL_KIND if any(h in url for h in hosts)), "other")
            found.setdefault(("url", kind, url), set()).add(section)
    return [{"type": t, "kind": k, "value": v, "sections": sorted(s)} for (t, k, v), s in sorted(found.items())]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("doi")
    ap.add_argument("--out")
    ap.add_argument("--file", type=pathlib.Path, help="local PDF / JATS XML / HTML / text of the paper")
    ap.add_argument("--no-suppl", action="store_true")
    a = ap.parse_args()

    doi = re.sub(r"^(https?://(dx\.)?doi\.org/|doi:)", "", a.doi.strip(), flags=re.I).lower()
    out = pathlib.Path(a.out or "extractions/" + re.sub(r"[^a-z0-9]+", "-", doi).strip("-"))
    out.mkdir(parents=True, exist_ok=True)

    print(f"OpenAlex: {doi}", file=sys.stderr)
    meta = openalex(doi)
    md, source, pmcid = None, None, None

    if a.file:
        md, source = local_file(a.file)
    if md is None:
        pmcid = europepmc_pmcid(doi)
        if pmcid:
            print(f"Europe PMC: {pmcid}", file=sys.stderr)
            try:
                md, source = jats_to_md(get(f"https://www.ebi.ac.uk/europepmc/webservices/rest/{pmcid}/fullTextXML")), "europepmc-jats"
            except Exception as e:
                print(f"  (Europe PMC full text unavailable: {e})", file=sys.stderr)
            if md is None:  # same JATS from NCBI; also covers author manuscripts Europe PMC lacks
                try:
                    xml = get(f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/efetch.fcgi?db=pmc&id={pmcid}")
                    if "<body" in xml:  # publisher-restricted records come back front matter only
                        md, source = jats_to_md(xml), "ncbi-pmc-jats"
                except Exception as e:
                    print(f"  (NCBI PMC full text unavailable: {e})", file=sys.stderr)
    if md is None and doi.startswith("10.1101/"):
        for server in ("biorxiv", "medrxiv"):
            coll = (get_json(f"https://api.biorxiv.org/details/{server}/{doi}") or {}).get("collection") or []
            if coll and coll[-1].get("jatsxml"):
                print(f"{server}: latest version {coll[-1].get('version')}", file=sys.stderr)
                try:
                    md, source = jats_to_md(get(coll[-1]["jatsxml"])), f"{server}-jats"
                    break
                except Exception as e:
                    print(f"  ({server} JATS failed: {e})", file=sys.stderr)
    if md is None and meta.get("pdf_url"):
        print(f"OA PDF: {meta['pdf_url']}", file=sys.stderr)
        try:
            pdf = out / "paper.pdf"
            pdf.write_bytes(get(meta["pdf_url"], binary=True))
            md, source = pdf_to_text(pdf), "oa-pdf"
        except Exception as e:
            print(f"  (PDF download failed, publishers often block scripts: {e})", file=sys.stderr)
    if md is None:
        md, source = f"# {meta.get('title') or doi}\n\n## Abstract\n\n{meta.get('abstract') or ''}\n", "abstract-only"

    meta["source"] = source
    meta["pmcid"] = pmcid
    if not a.no_suppl:
        meta["supplementary_files"] = fetch_suppl(doi, pmcid, out)

    (out / "fulltext.md").write_text(md)
    cands = candidates(md)
    for f in sorted(p for p in (out / "suppl").glob("*") if p.suffix in (".tsv", ".txt", ".csv")) if (out / "suppl").exists() else []:
        for c in candidates(f.read_text(errors="replace")):
            c["sections"] = [f"suppl/{f.name}"]
            cands.append(c)
    (out / "candidates.json").write_text(json.dumps(cands, indent=1))
    (out / "meta.json").write_text(json.dumps(meta, indent=1))

    n_acc = sum(c["type"] == "accession" for c in cands)
    print(f"{out}/: source={source}, {len(md.splitlines())} lines, {n_acc} accessions, "
          f"{len(cands) - n_acc} urls, {len(meta.get('supplementary_files') or [])} supplementary files")
    if source == "abstract-only":
        print("No full text reachable. Ask the user for the PDF and rerun with --file.", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
