# Data Sources And Provenance

The public `ClusterWeave` repository should treat project data as separate from the reusable pipeline.

Recommended policy:

- Keep reusable code and generic templates in-repo
- Store case-study tables under `examples/` only after redistribution review
- Regenerate public summaries from source systems where possible instead of committing derived exports with unclear terms

Current source-system categories in the originating workflow:

- NCBI Datasets genome downloads and assembly data reports
- local genome FASTA and annotation assets
- antiSMASH region GenBank outputs
- BiG-SCAPE clustering outputs
- ecology metadata normalizations
- optional NPLinker, GNPS, MassIVE, and PODP-derived tables

Notes:

- `prepare_genomes_from_accessions.sh` and the `scripts/ncbi/` helpers now regenerate the accession mapping directly from NCBI metadata.
- `Data/Genomes/Fungi/<project-name>/accessions_fungusID_taxonomyID.txt` includes genome size in Mb derived from the NCBI assembly report when available.

Before a public push:

- confirm which accession lists, metadata tables, and paired-omics exports can be redistributed
- add regeneration commands for each committed derived table
- capture access dates and version identifiers for downloaded reference datasets
