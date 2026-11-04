# Reproducibility

## Researcher records in result packages

New web result packages include `METHODS.md`, `run_metadata.json`,
`resources.tsv`, `CITATIONS.bib` and the distribution's `CITATION.cff` when
available. The methods document lists tools evidenced in the analysis, observed
versions and software/publication references. Failed current annotation attempts
retain their recorded versions and outcomes. Its annotation table identifies
excluded genomes and skipped detection; missing annotation is not evidence of
BGC absence. The JSON records staged GenBank
and source-input checksums, the captured source fingerprint, selected effective
parameters, processing timestamps and accession-cache producer identities.
The source fingerprint covers processing Python/shell/configuration files;
cache scientific producer hashes retain their separate contract. A release
citation alone does not identify modified source.

The package contains no raw environment dump, credentials, host paths or
producer-job relationships. Cached results retain their original scientific
producer hashes. A hit does not claim annotation or detection ran again.
BiG-SCAPE and downstream cohort work remain job-specific.

Detection v3 records the producer's CPU/concurrency allocation separately from
the current job's allocation. These scheduling values do not change the scientific
cache key; pinned dependencies, scientific parameters and partition policy do.

`resources.tsv` distinguishes native `wait4` CPU accounting from sampled
observations. Native CPU includes the stage process and waited descendants;
it excludes Docker daemon work and sibling tool containers. The native maximum
RSS is the largest individual-process peak, not the concurrent total. The
sampler observes the stage process group and containers carrying that job's
label, at a nominal one-second interval. Container CPU can miss short-lived
containers and final intervals. Summed RSS can double-count shared pages;
container memory usage can include filesystem cache. The combined sampled
memory value is explicitly not an exact physical-memory peak. Container image
digests are recorded when observed. Missing Docker access is reported as
unavailable and does not change scientific execution. Operators can disable
container observations with `CLUSTERWEAVE_RESOURCE_DOCKER_OBSERVATION=0`.

Processing wall time ends before packaging and excludes queue time and ZIP
compression. A canonical-workflow row combines its internal annotation,
detection, family analysis and summary tools. Optional follow-up commands have
separate rows. Resource limits and scheduler reservations remain distinct from
measured usage. Missing historical measurements are null or blank, never zero.
Historical tool versions and run releases are not inferred from the currently
installed distribution. An existing signed ZIP is preserved; an on-demand
package can add a report containing only available historical evidence.

The ZIP groups staged genomes by taxon under `input_gbks/bacteria/`,
`input_gbks/fungi/` or `input_gbks/unclassified/`. The internal staged files
remain at `input_gbks/<genome>.gbk`. The evidence index keeps its runtime-relative
`path` and adds `package_path`; the package checksum manifest names actual ZIP
members. Missing or conflicting taxon assignments are not guessed.

`ClusterWeave` is designed as a repo-first workflow, so the main reproducibility anchors are:

- a versioned Git tag or release archive
- the resolving DOI `https://doi.org/10.11578/PMI/dc.20260608.2`
- the accession list used to populate the genome root
- the env defaults or profile overrides used for the run
- the results-side provenance files written by `run_clusterweave.sh`

## Recommended Release Practice

1. Tag the GitHub release used for the publication-linked run.
2. Cite the resolving software DOI `https://doi.org/10.11578/PMI/dc.20260608.2` and the versioned `CITATION.cff`.
3. Record the exact `accessions.txt` used for the analysis.
4. Retain the generated `data/results/<project-name>/reproducibility/` directory in private run evidence. Before publishing a reviewer or release bundle, export only declared public summaries and remove or relativize operator-local paths.

## Layout Casing

The public source tree uses lowercase runtime roots: `data/genomes/fungi/<project-name>/`, `data/genomes/bacteria/<project-name>/`, `data/results/<project-name>/`, and `software/`. One canonical taxon manifest joins the explicit genome roots downstream.

## Canonical Run Provenance

When you run:

```bash
bash run_clusterweave.sh
```

When standard output is attached to a compatible terminal, the wrapper shows an
interactive stage tree for input preparation, annotation and BGC detection,
BiG-SCAPE, summary, clinker, figures, and the result package. Redirected or
piped output, CI, and `TERM=dumb` retain the canonical raw lines. Use
`bash run_clusterweave.sh --raw` when exact raw output is needed in an
interactive terminal. The display honors `NO_COLOR` and uses an ASCII tree when
the terminal locale cannot represent Unicode.

The wrapper writes:

- `data/results/<project-name>/reproducibility/run_clusterweave_manifest.tsv`
- `data/results/<project-name>/reproducibility/run_clusterweave_context.env`
- `data/results/<project-name>/reproducibility/external_artifacts.tsv`

These files capture the stage toggles, target genome, operator-local paths, Git revision information, and checksums for local external artifacts visible to the wrapper at run time. They are private provenance inputs, not automatically public package members.

Staged clinker panels use `--dont_set_origin` only when their GenBank inputs
prove circular-origin correction is unnecessary. Origin-spanning genes retain
clinker's correction. Repeated missing-parent-gene messages become one counted
CDS-coordinate summary per panel; CDS-only annotations are informational.
Other warnings, errors and unsuccessful exit statuses remain visible.

## External Artifacts

`external_artifacts.tsv` is written by `bin/capture_external_artifacts.py` at the end of the canonical wrapper when `CAPTURE_EXTERNAL_ARTIFACTS=1` (the default).

It records the source URI, operator-local path, version/tag, optional digest pin, SHA256 checksum, and byte size for key runtime artifacts such as:

- antiSMASH, FunBGCeX, BiG-SCAPE, funannotate, and clinker SIF files
- Pfam HMM files
- FastTree
- MiBIG GBK cache
- optional NPLinker base SIF when present

This keeps everyday defaults flexible while preserving the exact bytes used in a publication or reviewer run.

For stricter reruns, source `profiles/release_v1.0.0.env` from the repository root before running `run_clusterweave.sh`. The profile disables automatic mutable artifact acquisition so prepopulated bytes can be compared against `external_artifacts.tsv`.

## Figures

`run_figures.sh` renders the publication-facing BiG-SCAPE multipanel figure and graph-ready network exports:

```bash
bash run_figures.sh
```

The outputs are written under:

- `data/results/<project-name>/figures/`

The default figure layer writes:

- `fungi_big_scape_multipanel.svg` / `.png` when fungi are present
- `bacteria_big_scape_multipanel.svg` / `.png` when bacteria are present
- `bgc_overlap.svg`
- `bgc_overlap.png`
- `bigscape_network.graphml`
- `bigscape_network_node_attributes.tsv`
- `bigscape_network_edge_attributes.tsv`
- `phylogeny/clusterweave_taxon_tree.svg`
- `phylogeny/clusterweave_taxon_tree_leaf_profiles.tsv`
- `phylogeny/clusterweave_gcf_network_edges.tsv`
- `phylogeny/clusterweave_taxon_tree.graphml`
- `phylogeny/clusterweave_tree_bundle.zip`

The taxon-specific multipanel bar charts and fungal overlap figure use the condensed BGC categories `NRPS`, `PKS`, `RiPP`, `terpene`, `hybrid`, and `other`. Both multipanels share one visual grammar; bacterial panels omit the inapplicable FunBGCeX row. The overlap chart counts shared antiSMASH/FunBGCeX BGC calls once per class and splits tool-specific unshared calls by tool and class, with exploded tool-specific agreement slices connected to compact horizontal class bars. The detail bars use a fixed raw-count scale across the figure, show percent-of-union labels, and only include nonzero classes. The figure layer is intentionally lightweight: pure Python SVG/GraphML by default, with PNG conversion through `cairosvg` when available. Set `RUN_SUMMARY_FIGURES=1 KEEP_REDUNDANT_FIGURE_OUTPUTS=1` only when you need the older standalone summary/network side-products.

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

Executable version observations in `run_metadata.json` come from bounded probes of the selected native, immutable Docker image or SIF runtime. Configured image tags and runtime hashes are recorded separately. Output discovery includes clinker `panel.html` and successful optional-tool manifests; configuration alone does not establish use. New cache producers can retain sanitized version observations with their original execution provenance. A current executable version never fills a missing historical producer version, and existing signed packages remain unchanged.
