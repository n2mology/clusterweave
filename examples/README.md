# ClusterWeave Examples

This directory contains public-safe ClusterWeave example inputs and derived
outputs. They are suitable for documentation, walkthroughs, and lightweight
regression checks without republishing raw genome or tool working files.

## Layout

- `accessions.txt`
  - 50 fungal NCBI assembly accessions, one per line
- `accessions_fungusID_taxonomyID.txt`
  - generated accession mapping table with no header; columns are accession,
    normalized genome ID, taxonomy ID, genome size in Mb, organism name,
    taxonomy ID lineage, and taxonomy name lineage
- `summary/`
  - compact tables and Markdown summaries that show the workflow review surface
- `figures/`
  - `big_scape_multipanel.svg`
  - `bgc_overlap.svg`

## Scope

The example bundle includes only an accession list, the generated accession
mapping table, derived summaries, and rendered figures. It does not include
genome assemblies, BGC GenBank records, staged clinker inputs, raw
antiSMASH/FunBGCeX/BiG-SCAPE output trees, downloaded databases, containers,
caches, private job links, or large logs.

See `summary/README.md` for the per-file summary table descriptions.
