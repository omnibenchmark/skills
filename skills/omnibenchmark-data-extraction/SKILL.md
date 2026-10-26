---
name: omnibenchmark-data-extraction
description: "Given a DOI (or a local PDF when the paper is closed), extract the datasets a paper uses, with their accession numbers (GEO, SRA/ENA, ArrayExpress, EGA, Zenodo, Figshare...), and the methods with their code links, into a structured table aligned with the BEAD ontology (bead-core, bead-software). Also classify the paper as a method, benchmark, resource or other paper. Fetches text through OpenAlex, Europe PMC and bioRxiv, including supplementary tables, and checks every extracted item against the paper text. Use whenever the user gives a DOI or paper and asks which datasets or methods it uses, where its data or code is, whether it is a methods or benchmark paper, or wants material to scaffold an Omnibenchmark benchmark from the literature, even if they do not say 'extract' or 'BEAD'."
---

# Paper → datasets + code

The product is two lists a scaffold builder can trust: where each dataset can
be downloaded, and where each method's code lives. Each entry is checked
against the paper text (an accession, a URL or a verbatim quote), and what the
paper does not say is written down as a gap instead of guessed.

Metrics, tasks and which method ran on which dataset are out of scope. They
cost most of the reading (figure captions, metric definitions) and the scaffold
author decides them anyway. If the user asks for metrics, list the ones named
in the abstract in the reply, without checking them, and say that's all you did.

## 1. Fetch the text

```
python3 scripts/fetch_paper.py <DOI or doi.org URL>            # → extractions/<doi-slug>/
python3 scripts/fetch_paper.py <DOI> --file path/to/paper.pdf  # closed paper, user's copy
```

It tries Europe PMC full text (JATS), then NCBI PMC, then bioRxiv/medRxiv, then
the open-access PDF that OpenAlex lists. It writes `fulltext.md`,
`candidates.json` (every accession and URL with its section), `meta.json` and
`suppl/` (spreadsheets as one `.tsv` per sheet, docx/pdf as `.txt`).

- **Exit 3, `source=abstract-only`**: nothing open was reachable. Ask the user
  for the PDF and rerun with `--file`. Do not extract from the abstract.
- **`oa-pdf` / `local-pdf`** text wraps URLs across lines; check a truncated
  accession or URL against the PDF.
- **Missing supplements.** If the data list is "in Supplementary Table S1" and
  `suppl/` lacks it, ask the user for the file and save it into `suppl/`.

## 2. Read only what you need

Do not read `fulltext.md` end to end. Grep it.

1. **`candidates.json` first.** It already lists every accession and URL by
   section; references are excluded. Most of the extraction is assigning these.
2. **Abstract + last paragraph of the Introduction**: the paper type and the
   proposed method.
3. **Data availability / Code availability** sections.
4. **The Methods subsection that lists datasets or compared methods**, only
   where `candidates.json` leaves a dataset or method without a pointer.
5. **Supplementary tables**: open just the header and a few rows (`head`),
   then generate the table with a script (below). Do not read whole sheets.

## 3. Write the tables

Write `paper.tsv`, `datasets.tsv` and `methods.tsv` into
`extractions/<doi-slug>/tables/`. Columns are in
`references/extraction-schema.md`. Generate long tables from the supplement
with a short script kept in the extraction directory, never by typing them.

- **Paper type.** `method` if the paper introduces any method or tool;
  `benchmark` if it compares existing methods and introduces none; `resource`
  for databases, atlases and dataset collections; `other` otherwise. A method
  paper with competitors is still `method`. One-sentence reason.
- **One dataset row per dataset as the paper counts them.** Several can share
  an accession. Prefer the accession, then a DOI deposit (Zenodo, Figshare),
  then a portal URL; record the processed-data deposit when there is one.
- **Methods: role and code.** `proposed`, `compared`, `baseline` or `used`
  (run by a pipeline, not evaluated). Fill `tool_*` only from the text.
- **Do not invent.** No accession, URL or version that is not in the text.
  A missing pointer is a `gap` row in `paper.tsv`.
- **Evidence is cheap**: a dataset with an accession or a method with a
  `tool_url` needs no quote; the checker finds the id or URL in the text. Only
  entries without one need a 5–25-word verbatim `quote`.

## 4. Build and check

```
python3 scripts/to_bead.py extractions/<doi-slug>
```

It builds `extraction.json` and `extraction.ttl` (BEAD RDF) from the tables
and checks ids, the paper-type rule, and that every quote, accession and
tool URL occurs in the text. On errors, fix the tables and rerun. Never rerun
with `--no-quote-check` to make an error go away. Warnings become gap rows.

## 5. Report

Reply with the paper type and its rationale, the markdown summary `to_bead.py`
printed (paste it, do not retype it), the gaps, and the path
`extractions/<doi-slug>/`.

## Handing off to a scaffold

`datasets.tsv` → the data stage's modules, `methods.tsv` → the methods stage
(look up existing modules first, see `omnibenchmark-module`; write the plan
with `omnibenchmark-plan`). Tables of several papers concatenate cleanly.
