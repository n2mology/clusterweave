# Data Sources And Provenance

The public `ClusterWeave` repository separates reusable workflow source from project data and runtime artifacts. Source code, hosted web portal UI/API code, tests, templates, generic profiles, and curated example outputs are public-facing. Uploaded inputs, raw genomes, private ecology metadata, paired-omics assets, local databases, caches, container images, SIFs, full generated result archives, raw logs, and operator work directories remain private/runtime material.

Public examples under `examples/` are intentionally small, derived, and path-sanitized. They are suitable for demonstrating output shape and downstream interpretation, but they are not a substitute for the full private run directories used by operators.

Source-system categories used by the workflow include:

- NCBI Datasets genome downloads and assembly data reports
- Local genome FASTA and annotation assets supplied by an operator
- antiSMASH region GenBank outputs
- BiG-SCAPE clustering outputs
- Ecology metadata normalizations
- Optional NPLinker, GNPS, MassIVE, and PODP-derived tables

Provenance notes:

- `prepare_genomes_from_accessions.sh` and the `scripts/ncbi/` helpers regenerate accession mappings directly from NCBI metadata.
- `data/genomes/fungi/<project-name>/accessions_fungusID_taxonomyID.txt` includes genome size in Mb derived from the NCBI assembly report when available.
- `data/results/<project-name>/reproducibility/external_artifacts.tsv` records local artifact checksums for reruns. Treat it as internal provenance unless a public-safe variant is generated without local paths or restricted artifact details.
- Public markdown summaries should describe source tables with repository-relative labels such as `data/results/<project-name>/summary/...`, never workstation, cloud-sync, home-directory, or mount paths.

## Manuscript Availability Framing

Use this framing for manuscript and release handoff until the DOI resolver is active:

> The ClusterWeave source code, including command-line workflow scripts, Python helpers, hosted web portal UI/API code, build recipes, documentation, and public-safe example outputs, is available from the software repository and the reserved DOI https://doi.org/10.11578/PMI/dc.20260608.2 (pending activation). Uploaded inputs, private runtime job data, raw logs, local databases, generated full-result archives, container images/SIFs, caches, and restricted third-party assets are not distributed publicly. Public examples are curated, derived, and path-sanitized.

The default runtime layout is lowercase: `data/genomes/fungi/<project-name>/`, `data/results/<project-name>/`, and `software/`. Treat uppercase `Data/` or `Software/` paths as legacy operator overrides, not current public-release defaults.
