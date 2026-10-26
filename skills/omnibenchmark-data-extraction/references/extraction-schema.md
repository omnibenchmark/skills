# The extraction tables

The agent writes these tab-separated files into `<extraction dir>/tables/`.
`scripts/to_bead.py` reads them, builds `extraction.json` (do not edit it by
hand; it is regenerated on every run), checks it, and derives `extraction.ttl`
and the chat summary. Three tables: `paper.tsv`, `datasets.tsv`, `methods.tsv`.

Conventions: tab-separated with a header row; a cell that holds a list is
`;`-separated; ids are short kebab-case slugs, unique across all tables
(`scvi`, `pancreas-celseq`). Extra columns are allowed and ignored, so
keep any useful source columns (cell counts, platform) alongside.

Build long tables with a script rather than by typing them. For example,
`datasets.tsv` from a supplementary table:

```python
import csv
rows = csv.DictReader(open("suppl/Supplementary Table 1.tsv"), delimiter="\t")
with open("tables/datasets.tsv", "w") as out:
    out.write("id\tlabel\torganism\tmodality\taccessions\turls\n")
    for i, r in enumerate(rows):
        acc = ";".join(x for x in (f"GEO:{r['GSE_ID']}" if r["GSE_ID"] else "",
                                   f"SRA/ENA:{r['NCBI Accession']}" if r["NCBI Accession"] else "") if x)
        out.write(f"ds{i+1:03d}\t{r['Titile']}\t{r['Organism']}\t{r['Modality']}\t{acc}\t{r['Download_link']}\n")
```

The file names, column names and value formats below are what `to_bead.py`
reads. The examples are illustrative.

## paper.tsv: two columns, `field` and `value`

| field | value |
| --- | --- |
| `doi` | `10.1038/s41592-021-01336-8` |
| `title` | as published |
| `year` | `2021` |
| `type` | `method`, `benchmark`, `resource` or `other` (see below) |
| `type_rationale` | one sentence |
| `quote` | verbatim evidence for the type |
| `source` | `source` from meta.json |
| `gap` | one row per gap; repeat the field |

## methods.tsv: `id, label, role, introduced_here`, optional `quote, reference, tool_kind, tool_url, tool_registry, tool_identifier, tool_version`

- `role`: `proposed` (introduced here), `compared` (a competitor arm),
  `baseline` (trivial or control arm: random, unintegrated, PCA), `used` (run as
  part of a pipeline, not evaluated).
- `introduced_here`: `true` / `false`.
- `tool_kind`: `repository` (git URL in `tool_url`), `package` (with
  `tool_registry`: PyPI, CRAN, Bioconductor, conda-forge, bioconda, Docker Hub,
  and `tool_identifier`, the name there), or `software`. Version only if stated.
- `reference`: the citation marker as it appears in fulltext.md (`[21]`).
- `quote`: may be left empty when `tool_url` is set; the checker then requires
  the URL to occur in the paper or a supplement.

## datasets.tsv: `id, label`, optional `accessions, urls, organism, modality, notes, quote`

One row per dataset as the paper counts them, not per study. If one GEO series
holds three datasets the paper treats separately, that is three rows with the
same accession. A scaffold's data stage wants one entry per dataset it will run.

- `accessions`: `;`-separated `REPOSITORY:ID`, e.g.
  `GEO:GSE81076;SRA/ENA:PRJNA494734`. Repository names the checker validates:
  `GEO`, `SRA/ENA`, `ArrayExpress/BioStudies`, `EGA`, `dbGaP`, `PRIDE`, `Synapse`,
  `Zenodo`, `Figshare`, `Dryad`. Others are accepted unchecked.
- `urls`: `;`-separated landing pages, portals, DOIs that are not accessions.
  Record the processed-data deposit (Figshare/Zenodo `.h5ad`) when there is one,
  because a scaffold usually starts from it.
- `quote`: may be left empty when `accessions` is set. The checker then
  requires every accession id to occur in the paper or a supplement instead.
  A dataset with neither a quote nor accessions fails the check.

## Paper type

- `method`: introduces at least one method or tool (`introduced_here: true`).
  Comparing it against others does not make it a benchmark.
- `benchmark`: compares existing methods and introduces none. An evaluation
  harness or metric library built for the comparison (scIB) does not count as a
  method.
- `resource`: a database, atlas or dataset collection. Methods it runs go in
  with `role: used`.
- `other`: reviews, application papers, anything else.

The checker enforces `method` ⇔ some `introduced_here: true`.

## Mapping to BEAD (bead-core ≥ 0.2.0)

| table | bead | property |
| --- | --- | --- |
| paper | `bead:MethodPaper` / `bead:BenchmarkPaper` / `bead:ResourcePaper` / `bead:Paper` | `dcterms:title`, `bead:introduces` → method |
| methods | `bead:Method` | `bead:implementedIn` → tool |
| tool_* columns | `bead:Repository` / `bead:Package` / `schema:SoftwareApplication` | `schema:url`, `bead:hasVersion`, `bead:hasRegistryIdentifier`, `bead:isAvailableFrom` → `bead:SoftwareRegistry` |
| datasets | `bead:Dataset` | `dcterms:identifier` (`GEO:GSE81076`), `schema:url` |
