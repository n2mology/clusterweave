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

- [`examples/flavi19`](../examples/flavi19/): 19 versioned section *Flavi*
  assemblies from Kjærbølling et al. (2020), with source-study and current NCBI
  names preserved separately.
- [`examples/saccharopolyspora26`](../examples/saccharopolyspora26/): the exact
  26 versioned RefSeq assemblies in the public BGCFlow v0.9.0
  `mq_saccharopolyspora` example.

Both bundles prefer accession manifests and NCBI Datasets retrieval over genome
redistribution. Their tables retain public candidate coordinates, component
evidence, explicit analysis states, and aggregate selected-family assignment
coverage while omitting run-local family identifiers and private execution
metadata. Component predictions and similarity annotations are evidence rather
than biological ground truth.

The source, BSD-3-Clause license, and citation metadata are available from the
repository and [doi:10.11578/PMI/dc.20260608.2](https://doi.org/10.11578/PMI/dc.20260608.2).
