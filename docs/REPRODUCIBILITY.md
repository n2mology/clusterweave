# Reproducibility

`ClusterWeave` is designed as a repo-first workflow, so the main reproducibility anchors are:

- a versioned Git tag or release archive
- the reserved DOI `https://doi.org/10.11578/PMI/dc.20260608.2` once activated
- the accession list used to populate the genome root
- the env defaults or profile overrides used for the run
- the results-side provenance files written by `run_clusterweave.sh`

## Recommended Release Practice

1. Tag the GitHub release used for the manuscript.
2. Use the reserved software DOI `https://doi.org/10.11578/PMI/dc.20260608.2` once it is active; until then, cite the repository URL and `CITATION.cff`.
3. Record the exact `accessions.txt` used for the analysis.
4. Keep the generated `data/results/<project-name>/reproducibility/` directory with the release outputs.

## Layout Casing

The public source tree and generated defaults use lowercase runtime roots: `data/genomes/fungi/<project-name>/`, `data/results/<project-name>/`, and `software/`. Treat uppercase `Data/`, `Software/`, `Genomes/`, `Results/`, or `Fungi/` as legacy operator-specific overrides. For legacy reruns, set `DATA_ROOT`, `RESULTS_ROOT`, or `SOFTWARE_ROOT` explicitly instead of changing the public defaults.

## Canonical Run Provenance

When you run:

```bash
bash run_clusterweave.sh
```

the wrapper writes:

- `data/results/<project-name>/reproducibility/run_clusterweave_manifest.tsv`
- `data/results/<project-name>/reproducibility/run_clusterweave_context.env`
- `data/results/<project-name>/reproducibility/external_artifacts.tsv`

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

`run_figures.sh` renders the publication-facing BiG-SCAPE multipanel figure and graph-ready network exports:

```bash
bash run_figures.sh
```

The outputs are written under:

- `data/results/<project-name>/figures/`

The default figure layer writes:

- `big_scape_multipanel.svg`
- `big_scape_multipanel.png`
- `bgc_overlap.svg`
- `bgc_overlap.png`
- `bigscape_network.graphml`
- `bigscape_network_node_attributes.tsv`
- `bigscape_network_edge_attributes.tsv`

The multipanel bar chart and overlap figure use the condensed BGC categories `NRPS`, `PKS`, `RiPP`, `terpene`, `hybrid`, and `other`. The overlap chart counts shared antiSMASH/FunBGCeX BGC calls once per class and splits tool-specific unshared calls by tool and class, with exploded tool-specific agreement slices connected to compact horizontal class bars. The detail bars use a fixed raw-count scale across the figure, show percent-of-union labels, and only include nonzero classes. The figure layer is intentionally lightweight: pure Python SVG/GraphML by default, with PNG conversion through `cairosvg` when available. Set `RUN_SUMMARY_FIGURES=1 KEEP_REDUNDANT_FIGURE_OUTPUTS=1` only when you need the older standalone summary/network side-products.

The BiG-SCAPE network renderer is a pure-Python SVG/GraphML helper. It uses BiG-SCAPE `record_annotations.tsv`, `*_clustering_c*.tsv`, and `*_c*.network` files, preferring the `mix` category. Its default ecology metadata input is `data/results/<project-name>/summary_tables/ecofun_metadata_normalized.tsv`; user TSV/CSV files may also use `sample_id` or `fungal_id` plus `ecology_category`. Blank, unknown, or unlabeled ecology values do not draw a gray border unless at least one informative ecology category is present. When `summary/candidate_bgc_gcf_crosswalk.tsv` is present, the best representative dataset record with a MiBIG-style BGC accession annotation in each accession/family group receives a small blue dot; actual MiBIG reference GBKs receive a blue outer ring. Connected components are labeled with concise putative product names above antiSMASH ClusterCompare confidence percentages when available. MiBIG-only reference families are omitted by default. Optional PNG/PDF conversion is available when `cairosvg` is installed.

Useful controls:

```bash
RUN_BIGSCAPE_NETWORK_FIGURE=0 bash run_figures.sh
RUN_BGC_OVERLAP_FIGURE=0 bash run_figures.sh
FORCE=1 PROJECT_NAME=clusterweave_smoke bash run_figures.sh
BIGSCAPE_NETWORK_FORMATS=svg,graphml,png KEEP_REDUNDANT_FIGURE_OUTPUTS=1 bash run_figures.sh
BIGSCAPE_NETWORK_DISTANCE_THRESHOLD=0.25 bash run_figures.sh
BIGSCAPE_NETWORK_MAX_NODES=250 bash run_figures.sh
BIGSCAPE_NETWORK_CANVAS_WIDTH=1200 bash run_figures.sh
BIGSCAPE_NETWORK_INCLUDE_MIBIG_ONLY=1 bash run_figures.sh
```
