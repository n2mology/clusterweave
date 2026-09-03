# Public example data dictionary

## Shared files

- `summary.tsv`: one row per panel with accession, candidate, GCF-completion, component-evidence, synteny, and ordering aggregates. `distinct_selected_family_count` is an aggregate only; run-local family labels are intentionally omitted.
- `state_definitions.tsv`: the six mutually exclusive analysis states and their observed counts across routed component records and the 20 reviewable synteny panels per example. A zero observed count does not remove a state from the vocabulary.

## Files in each panel

- `accession_manifest.tsv`: versioned public assembly accession, taxon, source-panel label, current NCBI organism name, and NCBI Datasets URL. In the fungal table, `source_study_name` is preserved separately from current NCBI nomenclature.
- `candidates.tsv`: deterministic candidate order plus public component evidence. antiSMASH and FunBGCeX start/end fields are 1-based inclusive. `sequence_record` is a versioned sequence accession when antiSMASH supplied one; FunBGCeX-only rows may retain its normalized scaffold identifier. `detector_relation` is `shared`, `antismash_only`, or `funbgcex_only`; these are component-output relationships, not truth classes. `same_putative_product_*` is lexical component support, not product confirmation. `gcf_assignment_status` and aggregate family counts are retained without run-local identifiers.
- `candidate_reconciliation.tsv`: per-assembly candidate totals. For fungi, `candidate_rows = shared_overlap_rows + antismash_only_rows + funbgcex_only_rows`, `antismash_candidates = shared_overlap_rows + antismash_only_rows`, and `funbgcex_candidates = shared_overlap_rows + funbgcex_only_rows`. For bacteria, FunBGCeX is `taxonomically_inapplicable`, not a negative finding.
- `analysis_states.tsv`: component applicability, normalized analysis state, and feature count per assembly, plus the panel-level optional NPLinker state. Raw implementation statuses and evidence paths are intentionally absent.
- `gcf_completion.tsv`: reconciliation of candidate rows, staged antiSMASH regions, and selected-view assignments. `non_applicable_unassigned_rows` are rows without an antiSMASH region and therefore outside antiSMASH-derived GCF assignment; `applicable_unassigned_rows` is the supported completeness measure.
- `tool_versions.tsv`: user-facing component/resource versions and roles.
- `parameters.tsv`: validated routing, resource, component, harmonization, GCF-view, and stable-ordering parameters.
- `COMMANDS.md`: retrieval instructions and portable component command templates. Placeholders in angle brackets are user-selected paths or identifiers.

## Representative figures

- Each panel's `figures/` directory contains public SVGs and a local README defining the panels and interpretive limits.
- `*.taxon_tree.svg` combines taxonomic context, per-genome BGC and selected-GCF summaries, and a bounded pairwise GCF-sharing matrix. The per-genome shared percentage and pairwise Jaccard percentage have different denominators, as documented in each figures README.
- `*.bigscape_multipanel.svg` organizes component family, product, known-cluster, protein, and synteny evidence. It does not establish family correctness or metabolite production.
- `flavi19.bgc_overlap.svg` summarizes fungal candidate relationships as shared coordinate overlaps, antiSMASH-only rows, and FunBGCeX-only rows. These are component-output relationships, not truth classes.
- `focal_locus_aspirochlorine_bigscape_nodes.tsv` defines the 34 displayed nodes, public accessions, component annotations, colors, and editable coordinates. `focal_locus_aspirochlorine_bigscape_edges.tsv` defines the 86 displayed edges and their BiG-SCAPE metrics. `svg_edge_width = 0.8 + 2 × (1 − distance)`; geometric edge length is layout spacing rather than a calibrated relationship value.

## Editable focal loci

`flavi19/focal_locus_aspirochlorine/` contains the synteny-resolved fungal SVG and sanitized focal record, 12 displayed records, 380 CDS features, 38 FunBGCeX genes, and 1,270 protein alignments. Coordinates are 1-based inclusive. MIBiG BGC0001123.5 is the panel/reference accession; the staged GenBank record itself retains the internally unversioned accession BGC0001123, so both are reported.

`saccharopolyspora26/focal_locus_geosmin/` contains the synteny-resolved bacterial SVG and sanitized focal record, 20 displayed records, 358 CDS features, and 1,203 protein alignments. FunBGCeX is `taxonomically_inapplicable` for this record. The antiSMASH score of 100 is a component score, not 100% protein identity; the retained focal protein alignment is 0.58 identity and 0.71 similarity.

In both focal directories, identity and similarity are fractions from 0 to 1. Stable accessions, coordinates, component labels, and evidence are retained without run-local family identifiers.

## Analysis-state vocabulary

- `completed_with_detection`: applicable component completed and reported at least one feature.
- `completed_no_detection`: applicable component completed without reporting the feature; this is not a claim of biological absence.
- `taxonomically_inapplicable`: the taxon route makes the component inapplicable; this is neither zero nor failure.
- `failed_or_incomplete`: the applicable component failed or lacks completion evidence.
- `not_generated_or_unavailable`: the artifact was not requested, generated, retained, or available.
- `unresolved`: available evidence cannot support another classification.
