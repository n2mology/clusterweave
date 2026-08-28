# Changelog

## 1.0.3 - 2026-08-28

Patch release:

- Unified persisted public-result manifests and signed indexes under one 32 MiB
  read/write bound, with explicit rejection above that limit.
- Accepted only the exact antiSMASH no-CDS, no-gene, all-records-skipped shard
  outcome as empty when a successful sibling shard is available; other nonzero
  shard outcomes remain fatal.
- Added a bounded query-complete BiG-SCAPE browser database that retains the
  shipped network and family-alignment query domains without copying unrelated
  distance rows.
- Restored signed generated-result downloads, sequence copying, and safe
  external links through the authenticated parent while retaining opaque
  origins, bundle isolation, and the existing sandbox restrictions.
- Prevented generated BiG-SCAPE family controls from navigating away from the
  result and assigned finite SVG coordinates to singleton family trees.
- Replaced the broad generated examples with accession-defined section *Flavi*
  and *Saccharopolyspora* evidence bundles that omit genomes, private execution
  records, and run-local family identifiers.
- Made the process-cancellation and anonymous resource-policy tests
  deterministic across the public CI runner's shell timing and CPU count.

## 1.0.2 - 2026-07-31

Patch release:

- Added `CLUSTERWEAVE_MAX_ACCESSIONS=50` and
  `CLUSTERWEAVE_MAX_GENOME_FILES=50` to newly generated local configuration.
- Hydrated browser accession rows and file guidance from `public_quota`, with 50
  retained only as the disconnected fallback.
- Made accession-list imports atomic and derived related routing, ecology,
  taxonomy, accession-list, and accession-validation bounds from the configured
  input counts.
- Added synthetic acceptance and figure scaling coverage at 75 genomes without
  changing shipped profile defaults or claiming unrestricted scale.
- Consolidated duplicated annotation, NCBI renaming, summarization, runtime
  preparation, and browser-controller implementations behind one supported
  implementation for each responsibility.
- Added a shared hierarchical progress-tree contract for the browser and
  interactive CLI while preserving exact raw logs for automation and review.
- Preserved generated antiSMASH and FunBGCeX HTML navigation inside a
  scripts-only opaque-origin reader. Same-document region links stay local,
  while attested nested HTML resolves on trusted interaction without exposing a
  result access code or private worker path.
- Added generation-bound opaque result and artifact routes, signed result
  attestations, and bounded public projections for progress, accepted inputs,
  figures, result readers, and downloads.
- Improved mixed fungal and bacterial figure layout, BiG-SCAPE panel spacing,
  intrinsic TREE preview sizing, zoom and pan behavior, and taxon-aware result
  presentation.
- Refined result-access, run restoration, citation, upstream-credit, input
  validation, resource-limit, diagnostics, and waiting-game interfaces across
  desktop, narrow, keyboard, and reduced-motion layouts.

## 1.0.1 — 2026-07-23

Patch release:

- Added staged genome GenBank files, antiSMASH region GBKs, FunBGCeX BGC
  GenBanks, and a redacted checksummed evidence manifest to the authenticated
  full result package.
- Routed generated summary tables by selected taxa and ecology settings, and
  kept package-only evidence files out of the web result tabs.
- Kept package transfers active while another run is prepared and added
  background download progress.
- Reported antiSMASH region fan-out directly, retained one total job clock, and
  completed a genome with a warning when an applicable alternate detector
  succeeded.
- Corrected UTC handling for the total runtime clock and prevented prose or
  workflow-completion messages from being mistaken for protein sequences.
- Prevented a final in-flight rerun poll from issuing a duplicate result reload.

## 1.0.0 — 2026-07-23

Initial public release:

- Added authoritative fungi, bacteria, and mixed-input routing.
- Added bounded per-genome annotation/antiSMASH fan-out and progress reporting.
- Added bacterial Prodigal/antiSMASH support with taxon-aware downstream summaries.
- Added fungal and bacterial BiG-SCAPE multipanels plus taxonomy/BGC/GCF context outputs.
- Added sanitized authenticated HTML previews and a public-safe BiG-SCAPE SQLite viewer copy.
- Raised the public NCBI accession limit to 50.
- Added a loopback-only trusted local Docker profile for Linux, WSL2, and Docker Desktop.
- Added side-by-side 50-genome fungal and 40-genome mixed public examples.
