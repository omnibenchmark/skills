---
name: omnibenchmark-data-extraction
description: "Given a DOI (or a local PDF when the paper is closed), extract the datasets x methods x metrics a paper uses into a structured table aligned with the BEAD ontology (bead-core, bead-software), with dataset accession numbers (GEO, SRA/ENA, ArrayExpress, EGA, Zenodo, Figshare...) and code links, and classify the paper as a method, benchmark, resource or other paper. Fetches text through OpenAlex, Europe PMC and bioRxiv, including supplementary tables, and checks every extracted item against a verbatim quote. Use whenever the user gives a DOI or paper and asks which datasets, methods or metrics it uses, wants a benchmark's design pulled out of a paper, asks whether a paper is a methods or benchmark paper, wants accession numbers or data availability for a paper, or wants material to scaffold an Omnibenchmark benchmark from the literature, even if they do not say 'extract' or 'BEAD'."
---

# Paper → datasets × methods × metrics

The product is a table a scaffold builder can trust: which methods were run on
which datasets and scored with which metrics, where each dataset can be
downloaded, and where each method's code lives. Trust comes from two things:
every row points at a verbatim quote from the paper, and what the paper does not
say is written down as a gap instead of guessed.

Work in this order. The scripts do the network and parsing; your job is the
reading and the judgement in steps 2–3.

## 1. Fetch the text

```
python3 scripts/fetch_paper.py <DOI or doi.org URL>            # → extractions/<doi-slug>/
python3 scripts/fetch_paper.py <DOI> --file path/to/paper.pdf  # closed paper, user's copy
```

It tries Europe PMC full text (JATS), then NCBI PMC, then bioRxiv/medRxiv, then
the open-access PDF that OpenAlex lists. It writes `fulltext.md`,
`candidates.json` (every accession and URL with its section), `meta.json` and
`suppl/`, and prints the source it used. Supplementary files come from Europe
PMC's bundle or, failing that, the publisher's landing page. Spreadsheets
become one `.tsv` per sheet; docx and pdf become `.txt`.

- **Exit 3, `source=abstract-only`**: nothing open was reachable. Stop and ask
  the user for the PDF (or the publisher's HTML/XML), then rerun with `--file`.
  Do not extract from the abstract alone; the methods, datasets and metrics are
  not in it.
- **You can read PDFs yourself.** Still run `--file`: the evidence check in
  step 4 needs a text copy of the paper, and the same flow then works for
  models that cannot read PDFs.
- **`oa-pdf` or `local-pdf`** text loses tables and wraps URLs across lines.
  Check accessions and URLs against the PDF when one looks truncated.
- **Missing supplements.** Publisher sites behind a bot wall return nothing. If
  the data or method list is "in Supplementary Table S1" and `suppl/` lacks it,
  say so and ask the user for the file. Save it into `suppl/` as
  `.tsv`/`.csv`/`.txt` so the checker can see it.

## 2. Read in this order

1. **Abstract, Introduction (last paragraph), Discussion (first paragraph).** These
   tell you the paper type: "we present X" versus "we compare N methods".
2. **Data availability / Accession codes**, then `candidates.json`. Accessions
   in a references section are cited papers' data and are already excluded.
3. **Methods**: the dataset subsections, the list of compared methods (often
   with versions and parameters), and the metric definitions (often one
   subsection per metric).
4. **Supplementary tables** in `suppl/*.tsv`. Large dataset or method lists
   live here, especially in resource and benchmark papers.
5. **Figure and table captions**, to find which methods × datasets × metrics
   actually appear together (one comparison per figure panel or table).
6. **Code availability**, for repository URLs and package names.

## 3. Write the tables

Write tab-separated tables into `extractions/<doi-slug>/tables/`: `paper.tsv`,
`tasks.tsv`, `methods.tsv`, `datasets.tsv`, `metrics.tsv`, `comparisons.tsv`.
The columns, formats and BEAD mapping are in `references/extraction-schema.md`.
Read it first. Do not write `extraction.json` by hand. The next step builds
it from the tables.

**Generate long tables with a short script, never by typing them.** A dataset
list in a supplementary table becomes `datasets.tsv` in a few lines of Python
(there is an example in the schema reference). The supplement is the source and
the accessions are checked against it. Keep the script in the extraction
directory so the step can be rerun.

The judgement calls:

- **Paper type.** `method` if the paper introduces any method or tool it
  evaluates; `benchmark` if it compares existing methods and introduces none;
  `resource` for databases, atlases and dataset collections; `other` otherwise.
  A method paper that compares its method against five others is still a
  `method` paper. Its competitors become `compared` arms, which is what a
  scaffold wants. Give the reason in one sentence.
- **One row per dataset**, as the paper counts them, not per study or
  accession. Several datasets can share a GEO series; repeat the accession.
- **Comparisons follow the paper's result blocks.** `table.tsv` expands each
  comparison into every dataset × method × metric combination. Where the paper
  ran only some methods on some datasets (a scaling test with two survivors,
  an ATAC-only subset), make that its own comparison. Do not go further and
  work out which metric is applicable to which method output; that belongs to
  the scaffold, not the extraction.
- **Datasets: point at the downloadable thing.** Prefer, in order: the
  accession (GSE…, PRJNA…, E-MTAB-…, EGAS…), then a DOI deposit (Zenodo,
  Figshare), then a portal URL. Record the processed-data deposit too when the
  authors share one. A scaffold usually starts from it. "Available on request"
  or no pointer at all is a `gap` row in `paper.tsv`.
- **Do not invent.** No version, URL or accession that is not in the text. A
  method with no code link gets empty `tool_*` cells and a gap row. The user
  can look it up; an invented link is worse than a missing one.
- **Evidence.** Each row's `quote` is 5–25 words copied verbatim from
  `fulltext.md` or `suppl/`. Dataset rows with accessions may leave `quote`
  empty, because then their accession ids are what gets checked.

## 4. Build, check and render

```
python3 scripts/to_bead.py extractions/<doi-slug>
```

It builds `extraction.json` from the tables, then checks ids,
cross-references, the paper-type rule and that every quote and accession is
really in the text. It writes `table.tsv` (long form, one row per comparison ×
dataset × method × metric) and `extraction.ttl` (BEAD RDF), and prints a
markdown summary. On errors, fix the tables (or the script that generates them)
and rerun. Never rerun with `--no-quote-check` to make an error go away. A
quote that is not found means the item is not supported yet. Treat warnings
(dataset without a pointer, odd-looking accession) as gap rows.

## 5. Report

Reply with:

1. The paper type and its one-line rationale.
2. The markdown summary `to_bead.py` printed (comparisons table, datasets
   table with accessions). Paste it; do not retype it.
3. The gaps, as a short list.
4. The paths: `extractions/<doi-slug>/tables/`, `extraction.json`, `table.tsv`, `extraction.ttl`.

## Handing off to a scaffold

`table.tsv` rows map onto an Omnibenchmark plan: distinct `dataset` values →
the data stage's modules, `method` → the methods stage, `metric` → the metrics
stage. Before any module is written, look up existing modules for each method
(see `omnibenchmark-module`). To write the plan, use `omnibenchmark-plan`. The
TSVs of several papers concatenate cleanly (same columns, `doi` first), which is
how to build a scaffold from a literature set rather than one paper.
