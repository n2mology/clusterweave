# Mixed-example summary outputs

This folder contains compact, derived outputs from the completed 20-bacteria /
20-fungi canonical run. The tables preserve the workflow's taxon and detector
applicability semantics while remaining suitable for documentation and tests.

## Files

- `all_tools_bgc_comparison.csv`
  - normalized per-BGC comparison of antiSMASH and FunBGCeX calls, including
    taxon group, overlap coordinates, class labels, and annotation hints
- `all_tools_shared_unshared_summary.csv`
  - aggregate shared, unshared, and not-applicable caller/GCF counts by genome,
    tool, entity type, and normalized class
- `family_atlas_shortlist.md`
  - review-oriented dataset-wide family candidates with conservative
    interpretation text
- `family_atlas_shortlist.tsv`
  - tabular form of the family-atlas shortlist for reproducible review

FunBGCeX is fungal-only. Its bacterial comparison fields are empty or marked
not applicable rather than being interpreted as missing detections.

## Excluded

This repository-safe summary snapshot excludes genome and sequence files,
per-region GenBank files, full third-party output trees, databases, logs,
caches, private result metadata, and machine-specific paths. The authenticated
**Download package** from a completed run serves a different purpose: it keeps
the staged genome and BGC GenBank files together with their redacted checksum
manifest for further review.
