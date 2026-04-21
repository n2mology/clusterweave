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

These files capture the stage toggles, target genome, paths, and Git revision information visible to the wrapper at run time.

## Figures

`run_figures.sh` renders a small set of publication-friendly PNG figures directly from the summary tables:

```bash
bash run_figures.sh
```

The outputs are written under:

- `Data/Results/<project-name>/figures/`

The figure layer is intentionally lightweight and base-R only so it does not add a large plotting dependency burden for first-time users.
