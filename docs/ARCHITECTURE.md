# Architecture

`ClusterWeave` is currently a shell-first workflow with Python helper scripts.

Execution flow:

1. `accessions.txt`
2. `install_ncbi_cli.sh` (optional setup helper)
3. `prepare_genomes_from_accessions.sh`
4. Optional env overrides from `config/defaults.env` or a case-study profile
5. `run_clusterweave.sh`
6. `run_annotation_and_detection.sh`
7. `run_bigscape.sh`
8. `summarize_clusterweave.sh`
9. Atlas-first `run_clinker.sh`, with optional target-aware clinker tracks when `TARGET_GENOME` is set
10. Optional `run_nplinker.sh`

Python helper responsibilities:

- `build_bgc_gcf_crosswalk.py`: join summary outputs to BiG-SCAPE families
- `build_candidate_tables.py`: optional ecology-aware ranking and reviewer shortlist generation
- `export_dataset_family_atlas.py`: dataset-wide BiG-SCAPE family atlas export for no-target clinker staging
- `render_bigscape_network.py`: BiG-SCAPE record network SVG and Cytoscape GraphML export
- `export_priority_shortlist.py`: target-genome shortlist extraction
- `export_shared_family_shortlist.py`: shared-family shortlist extraction
- `stage_clinker_panels.py`: comparator selection and panel staging

NCBI bootstrap responsibilities:

- `scripts/ncbi/download_ncbi_genomes.sh`: per-accession downloads from NCBI Datasets
- `scripts/ncbi/rename_ncbi_genomes.sh`: derive stable fungus IDs and rename package contents
- `scripts/ncbi/flatten_ncbi_genomes.sh`: flatten renamed package outputs into the genome root

Near-term refactor target:

- move helper logic into `src/clusterweave/`
- keep shell scripts thin wrappers only

Web/runtime notes:

- `web/canonical_pipeline.py` is the current bridge from web jobs into the canonical shell scripts.
- The lab QA runtime uses `ENGINE=docker` with a host Docker socket only in `docker-compose.yml`.
- Public hosted deployments should keep the web/API layer as the central orchestrator and move heavy stages into constrained, prebuilt worker images.
- See `docs/WEB_RUNTIME.md` for the runtime strategy, stage DAG boundary, and socket-safety rules.
