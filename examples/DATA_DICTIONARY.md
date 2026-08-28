# Public example data dictionary

## Shared files

- `summary.tsv`: one row per panel with accession, candidate, GCF-completion, component-evidence, synteny, and ordering aggregates. `distinct_selected_family_count` is an aggregate only; run-local family labels are intentionally omitted.
- `state_definitions.tsv`: the six mutually exclusive analysis states and their observed counts across routed component records and the 20 reviewable synteny panels per example. A zero observed count does not remove a state from the vocabulary.

## Files in each panel

- `accession_manifest.tsv`: versioned public assembly accession, taxon, source-panel label, current NCBI organism name, and NCBI Datasets URL. In the fungal table, `source_study_name` is preserved separately from current NCBI nomenclature.
- `candidates.tsv`: deterministic candidate order plus public component evidence. antiSMASH and FunBGCeX start/end fields are 1-based inclusive. `sequence_record` is a versioned sequence accession when antiSMASH supplied one; FunBGCeX-only rows may retain its normalized scaffold identifier. `detector_relation` is `shared`, `antismash_only`, or `funbgcex_only`; these are component-output relationships, not truth classes. `same_putative_product_*` is lexical component support, not product confirmation. `gcf_assignment_status` and aggregate family counts are retained without run-local identifiers.
- `candidate_reconciliation.tsv`: per-assembly candidate totals. For fungi, `candidate_rows = shared_overlap_rows + antismash_only_rows + funbgcex_only_rows`, `antismash_candidates = shared_overlap_rows + antismash_only_rows`, and `funbgcex_candidates = shared_overlap_rows + funbgcex_only_rows`. For bacteria, FunBGCeX is `taxonomically_inapplicable`, not a negative finding.
- `analysis_states.tsv`: component applicability, normalized analysis state, and feature count per assembly, plus the panel-level optional NPLinker state. Raw implementation statuses and private evidence paths are intentionally absent.
- `gcf_completion.tsv`: reconciliation of candidate rows, staged antiSMASH regions, and selected-view assignments. `non_applicable_unassigned_rows` are rows without an antiSMASH region and therefore outside antiSMASH-derived GCF assignment; `applicable_unassigned_rows` is the supported completeness measure.
- `tool_versions.tsv`: user-facing component/resource versions and roles.
- `parameters.tsv`: validated routing, resource, component, harmonization, GCF-view, and stable-ordering parameters.
- `COMMANDS.md`: retrieval instructions and portable component command templates. Placeholders in angle brackets are user-selected paths or identifiers.

## Fungal focal locus

`flavi19/focal_locus_aspirochlorine/` contains the approved SVG and its sanitized editable records, CDS features, FunBGCeX genes, and protein alignments. Coordinates are 1-based inclusive. Identity and similarity are fractions from 0 to 1. MIBiG BGC0001123.5 is the panel/reference accession; the staged GenBank record itself retains the internally unversioned accession BGC0001123, so both are reported.

## Analysis-state vocabulary

- `completed_with_detection`: applicable component completed and reported at least one feature.
- `completed_no_detection`: applicable component completed without reporting the feature; this is not a claim of biological absence.
- `taxonomically_inapplicable`: the taxon route makes the component inapplicable; this is neither zero nor failure.
- `failed_or_incomplete`: the applicable component failed or lacks completion evidence.
- `not_generated_or_unavailable`: the artifact was not requested, generated, retained, or available.
- `unresolved`: available evidence cannot support another classification.
