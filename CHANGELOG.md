# Changelog

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
