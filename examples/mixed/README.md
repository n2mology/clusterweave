# Mixed fungi/bacteria example

This public v1.0.0 example contains 20 bacterial RefSeq assemblies followed by
20 fungal assemblies. `accessions.txt` is the reproducible input list. The two
`accessions_*ID_taxonomyID.txt` files record the generated genome identifiers,
assembly sizes, NCBI taxids, and taxonomy lineages used for domain-aware
routing. Genome identifiers follow the same organism/strain naming policy in
both domains; taxon routing is recorded as metadata rather than encoded in an
identifier prefix.

All 40 accessions were verified against NCBI on 2026-07-16. The canonical run
completed on 2026-07-22 with project `example`, scope `Both`, no target genome,
ecology disabled, and the v1.0.0 defaults. Its input matched the verified
list exactly, so no accession substitutions were required.

The accession list and both generated taxon maps are locked v1.0.0 inputs.
These inputs and derived outputs must not be edited in place; a correction
belongs to a later version with explicit provenance.

## Curated outputs

The `figures/` directory contains four public-safe SVGs:

- `fungi_big_scape_multipanel.svg`: fungal antiSMASH, FunBGCeX, and GCF views;
- `bacteria_big_scape_multipanel.svg`: bacterial antiSMASH and GCF views;
- `bgc_overlap.svg`: applicability-aware detector overlap by genome;
- `clusterweave_taxon_tree.svg`: taxonomy context with BGC/GCF profiles and
  network arcs.

The `summary/` directory contains the normalized BGC comparison, shared and
unshared counts, and the dataset-wide family-atlas shortlist in tabular and
review-oriented Markdown forms. FunBGCeX fields are not applicable to bacterial
genomes and remain empty or explicitly marked as such.

No job ID, result token, private URL, raw genome, third-party result tree,
database, log, cache, or machine path is included.
