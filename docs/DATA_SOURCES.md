# Data sources and provenance

This reference describes the input, derived-data, and public-example provenance
boundaries. Run-level recording requirements are documented in
[REPRODUCIBILITY.md](REPRODUCIBILITY.md).

ClusterWeave accepts NCBI GenBank/RefSeq assembly accessions and bounded
user-supplied FASTA or GenBank genomes. NCBI Datasets assembly and taxonomy
reports are authoritative for accession routing. User declarations are used
only where authoritative taxonomy is absent.

The canonical job layout separates fungal and bacterial genome roots and writes
one taxon manifest for downstream tools. Derived sources include antiSMASH and
FunBGCeX BGC calls, BiG-SCAPE GCF assignments, clinker synteny, normalized
taxonomy/ecology tables, MiBIG references when configured, and optional bounded
sequence evidence.

Each run records tool versions, settings, checksums, route/applicability status,
and public-safe artifact manifests. Raw genomes, raw tool result trees,
databases, caches, logs, private metadata, result tokens, and operator paths are
not public release artifacts.

The public examples are intentionally curated:

- `examples/fungi_only`: retained 50-genome fungal accession set and derived
  fungal outputs.
- `examples/mixed`: 20 current bacterial RefSeq plus 20 current fungal
  assemblies, verified 2026-07-16 and processed together in the completed
  canonical run, with both taxon maps and derived taxon-aware outputs.

A zero-BGC assembly remains scientifically valid input. Mixed-example
substitution occurs only for an accession-specific download or assembly failure
and must use a current annotated RefSeq assembly from the same species or
nearest represented lineage with the substitution documented.

The source, BSD-3-Clause license, and citation metadata are available from the
repository and [doi:10.11578/PMI/dc.20260608.2](https://doi.org/10.11578/PMI/dc.20260608.2).
