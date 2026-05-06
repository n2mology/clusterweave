# Install Notes

## Platform Contract

- Primary target: Linux or WSL with Bash
- Container engine: Singularity or Apptainer
- Python: 3.10+

## Required Inputs

- genomes under `Data/Genomes/Fungi/<project-name>/`
- container images or local tool installs for the modules you plan to run

## Recommended Setup

1. Edit `accessions.txt`.
2. Install the NCBI CLI with `bash install_ncbi_cli.sh` or place `datasets` / `dataformat` in `Software/ncbi_cli/`.
3. Run `bash prepare_genomes_from_accessions.sh`.
   This writes `accessions_fungusID_taxonomyID.txt` with accession, normalized genome ID, taxonomy ID, and genome size in Mb.
4. Run `bash run_clusterweave.sh` for the canonical end-to-end workflow.
5. By default, missing containers and several runtime resources will be pulled or built automatically; if you prefer stricter reproducibility, pin and preinstall them ahead of time.
6. Stage 1 prefers containerized FunBGCeX execution. It will use `FUNBGCEX_SIF` first, and if that file is missing it will build `Software/funbgcex/funbgcex_bundle.sif` from the repo-owned `Singularity.def`. The local Python bootstrap remains available only as an advanced opt-in fallback.
7. `run_clusterweave.sh` now auto-includes `run_clinker.sh` in atlas-first mode unless `RUN_STAGE_CLINKER=0`. Leave `TARGET_GENOME` unset for a dataset-wide family-atlas clinker run, or set it when you want targeted priority/shared-family clinker tracks as well. Set `RUN_CLINKER=0` only when you want to stage panels without executing clinker.
8. `bash summarize_clusterweave.sh` writes the core BGC comparison outputs by default when you want to rerun summaries without earlier stages.
9. Set `RUN_ECOLOGY_ANALYSIS=1` only when you want ecology-aware grouping, candidate ranking, and reviewer-shortlist outputs.
10. Curate `summary_tables/ecofun_metadata_normalized.tsv` if you want ecology labels to drive that optional analysis. A project-local editable scaffold is written to `summary_tables/ecofun_metadata_template.tsv` when metadata is auto-normalized, and the static repo header template remains at `config/metadata_template.tsv`.
11. Set `FOCUS_ECOLOGY_LABEL` if you want one ecology label treated as the prioritization focus instead of relying on the target genome's ecology.
12. Optionally run `bash run_figures.sh` to render lightweight figures from the generated tables. The summary plot compares per-genome antiSMASH and FunBGCeX BGC calls using the condensed categories `NRP`, `PKS`, `RiPP`, `Terpene`, `Hybrid`, and `Other`.
13. The canonical wrapper writes a small provenance bundle under `Data/Results/<project-name>/reproducibility/`, including `external_artifacts.tsv` with checksums for local SIFs, Pfam, FastTree, MiBIG, and related runtime artifacts.

## Optional Configuration

- `config/defaults.env` is a reference sheet for supported env vars; you do not need to copy it to start.
- `profiles/example_project.env` is a generic example profile, not a required runtime dependency.
- The main wrapper now uses `RUN_STAGE_ANNOTATION`, `RUN_STAGE_BIGSCAPE`, `RUN_STAGE_SUMMARY`, and `RUN_STAGE_CLINKER` as the public stage toggles.
- `RUN_CLINKER=1` is the intentional default inside Stage 4; use `RUN_CLINKER=0` for staging-only runs.
- `TARGET_GENOME` is optional and only needed when you want target-specific summary or clinker outputs.
- `PROJECT_NAME` is the main namespace for separating one project from another inside the same clone.
- `ACCESSIONS_FILE` lets you keep a different accession list for each project.
- `CAPTURE_EXTERNAL_ARTIFACTS=1` writes post-run checksums to the project-local reproducibility directory.

## Current Limitations

- Some modules still download external resources if missing.
- The NPLinker stage remains optional and network-sensitive.
- A bundled mini example dataset is not yet included.
- The NCBI genome bootstrap is accession-driven and intentionally enforces `download -> rename -> flatten`.
