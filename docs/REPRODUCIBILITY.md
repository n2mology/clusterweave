# Reproducibility

`ClusterWeave` is designed as a repo-first workflow, so the main reproducibility anchors are:

- a versioned Git tag or release archive
- the accession list used to populate the genome root
- the env defaults or profile overrides used for the run
- the results-side provenance files written by `run_clusterweave.sh`

## Recommended Release Practice

1. Tag the GitHub release used for the manuscript.
2. Archive the release with Zenodo if you want a DOI-backed software citation.
3. Record the exact `accessions.txt` used for the analysis.
4. Keep the generated `Data/Results/<project-name>/reproducibility/` directory with the release outputs.

## Canonical Run Provenance

When you run:

```bash
bash run_clusterweave.sh
```

the wrapper writes:

- `Data/Results/<project-name>/reproducibility/run_clusterweave_manifest.tsv`
- `Data/Results/<project-name>/reproducibility/run_clusterweave_context.env`
- `Data/Results/<project-name>/reproducibility/external_artifacts.tsv`

These files capture the stage toggles, target genome, paths, Git revision information, and checksums for local external artifacts visible to the wrapper at run time.

## External Artifacts

`external_artifacts.tsv` is written by `bin/capture_external_artifacts.py` at the end of the canonical wrapper when `CAPTURE_EXTERNAL_ARTIFACTS=1` (the default).

It records the source URI, local path, version/tag, optional digest pin, SHA256 checksum, and byte size for key runtime artifacts such as:

- antiSMASH, FunBGCeX, BiG-SCAPE, funannotate, and clinker SIF files
- Pfam HMM files
- FastTree
- MiBIG GBK cache
- optional NPLinker base SIF when present

This keeps everyday defaults flexible while preserving the exact bytes used in a manuscript or reviewer run.

For stricter reruns, source `profiles/release_v0.1.0.env` from the repository root before running `run_clusterweave.sh`. That profile keeps the smoke-run tool URIs visible for provenance but disables automatic pulls/downloads so a rerun uses prepopulated local artifacts that can be compared against `external_artifacts.tsv`.

## Figures

`run_figures.sh` renders a small set of publication-friendly PNG figures directly from the summary tables:

```bash
bash run_figures.sh
```

The outputs are written under:

- `Data/Results/<project-name>/figures/`

The current figure layer writes:

- `bgc_calls_by_tool_category.png`
- `shared_vs_unshared_bgc_calls.png`

These figures use the condensed BGC categories `NRP`, `PKS`, `RiPP`, `Terpene`, `Hybrid`, and `Other`. The figure layer is intentionally lightweight and base-R only so it does not add a large plotting dependency burden for first-time users.
