# Fungi-only summary outputs

This folder contains compact, derived ClusterWeave summary outputs. The files
are intended as examples of the workflow review surface and as
small tabular artifacts for downstream documentation or tests.

## Files

- `all_tools_bgc_comparison.csv`
  - normalized per-BGC comparison of antiSMASH and FunBGCeX calls, including
    overlap coordinates, class labels, annotation hints, and product matches
- `all_tools_shared_unshared_summary.csv`
  - aggregate shared and unshared caller/GCF counts by genome, tool, entity
    type, and normalized class
- `family_atlas_shortlist.md`
  - shortlist of dataset-wide family atlas candidates with
    conservative interpretation text
- `family_atlas_shortlist.tsv`
  - tabular form of the atlas shortlist for reproducible review

## Excluded

This repository-safe example summary intentionally excludes genome and sequence
files, per-region GenBank files, full third-party tool output trees, detailed
ecology metadata tables, temporary working directories, downloaded databases,
container artifacts, private job links, and large logs. The authenticated
**Download package** from a completed run serves a different purpose: it keeps
the staged genome and BGC GenBank files together with their redacted checksum
manifest for further review.
