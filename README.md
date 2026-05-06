# ClusterWeave

`ClusterWeave` is a workflow for biosynthetic target discovery and prioritization. It assembles annotation, BGC detection, BiG-SCAPE family context, shortlist generation, and clinker-ready panel staging into one reproducible workflow.

The repository is organized as a standalone workflow so it can be versioned and shared.

## Scope

- Stage 1: annotation plus antiSMASH and FunBGCeX via `run_annotation_and_detection.sh`
- Stage 2: BiG-SCAPE family inference via `run_bigscape.sh`
- Stage 3: core summary-table generation via `summarize_clusterweave.sh`
- Optional within Stage 3: ecology-aware ranking and reviewer shortlist generation with `RUN_ECOLOGY_ANALYSIS=1`
- Stage 4: dataset-wide clinker family-atlas staging and clinker execution by default, with optional target-aware synteny panels via `run_clinker.sh`
- Optional: NPLinker exploratory paired-omics follow-up via `run_nplinker.sh`

## Repository Layout

- `bin/`: Python helpers used by the shell entrypoints
- `config/`: default templates and env examples
- `profiles/`: example profiles and overrides
- `docs/`: install, release, and reproducibility notes
- `examples/`: public-safe example context or example-output bundles for docs and releases
- `manuscript/application_note/`: publication-facing notes and outline assets
- `tests/`: automated repo validation; these are software checks, not biological example data
- `Data/`: expected input and output layout for a standalone clone
- `Software/`: location for local containers, caches, and optional third-party tools
- `docs/REPRODUCIBILITY.md`: run provenance and figure-rendering notes

## Default Standalone Layout

`ClusterWeave` now assumes the repository root itself is the default project root:

- `Data/Genomes/Fungi/<project-name>/`
- `Data/Results/<project-name>/`
- `Software/`

If you prefer a larger shared monorepo, override paths with env vars such as `PROJECTS_ROOT`, `DATA_ROOT`, `RESULTS_ROOT`, and `SOFTWARE_ROOT`.

## Quick Start

1. Edit [accessions.txt](accessions.txt). This is the intended first manual input.
2. If you are new to GitHub, WSL, or the command line, start with [BEGINNER_SETUP.md](BEGINNER_SETUP.md).
3. Review [docs/INSTALL.md](docs/INSTALL.md).
4. Optionally install the NCBI CLI binaries into `Software/ncbi_cli/`:

```bash
bash install_ncbi_cli.sh
```

5. Populate the genome root from NCBI:

```bash
bash prepare_genomes_from_accessions.sh
```

This step writes `Data/Genomes/Fungi/<project-name>/accessions_fungusID_taxonomyID.txt`.
The mapping now includes:

- accession
- normalized genome ID
- taxonomy ID
- genome size in Mb

6. Run the canonical workflow:

```bash
bash run_clusterweave.sh
```

`run_clusterweave.sh` runs annotation/detection, BiG-SCAPE, summary generation, clinker staging, and clinker execution in one pass. The default clinker behavior is a dataset-wide atlas run.

If you also set `TARGET_GENOME`, the same stage adds targeted clinker tracks for that genome:

```bash
TARGET_GENOME=Your_Target_Genome_ID bash run_clusterweave.sh
```

## Running More Than One Project

Yes. `PROJECT_NAME` is the main switch that separates one `ClusterWeave` run from another.

When you set a new `PROJECT_NAME`, `ClusterWeave` writes to a different project-specific genome root and results root:

- `Data/Genomes/Fungi/<project-name>/`
- `Data/Results/<project-name>/`

In practice, a separate project usually means:

- a different `PROJECT_NAME`
- a different accession list, passed through `ACCESSIONS_FILE`
- optionally a different `TARGET_GENOME`

Example:

```bash
PROJECT_NAME=project_alpha ACCESSIONS_FILE=$PWD/accessions_project_alpha.txt bash prepare_genomes_from_accessions.sh
PROJECT_NAME=project_alpha bash run_clusterweave.sh

PROJECT_NAME=project_beta ACCESSIONS_FILE=$PWD/accessions_project_beta.txt bash prepare_genomes_from_accessions.sh
PROJECT_NAME=project_beta bash run_clusterweave.sh
```

If you reuse the same repository for several studies, this is the recommended pattern.

## Optional Configuration

You do not need to copy an env file to get started.

- [config/defaults.env](config/defaults.env) is a reference sheet of supported knobs.
- [profiles/example_project.env](profiles/example_project.env) is a generic example profile, not a required starting point.
- Use env files or inline vars only when you need to override paths, resources, or analysis behavior.

Common examples:

```bash
TARGET_GENOME=Your_Target_Genome_ID bash run_clusterweave.sh
RUN_ECOLOGY_ANALYSIS=1 TARGET_GENOME=Your_Target_Genome_ID bash summarize_clusterweave.sh
CLINKER_MODE=targeted TARGET_GENOME=Your_Target_Genome_ID bash run_clinker.sh
```

## Common Follow-Ups

Run the summary stage directly when you want to regenerate tables without rerunning earlier stages. By default, this keeps the focus on tool outputs and writes the core BGC comparison tables plus the BiG-SCAPE crosswalk:

```bash
bash summarize_clusterweave.sh
```

If you want ecology-aware prioritization and reviewer-facing shortlist outputs, set `RUN_ECOLOGY_ANALYSIS=1` and `TARGET_GENOME`:

```bash
RUN_ECOLOGY_ANALYSIS=1 TARGET_GENOME=Your_Target_Genome_ID bash summarize_clusterweave.sh
```

If ecology metadata has not been normalized yet, `summarize_clusterweave.sh` scaffolds
`summary_tables/ecofun_metadata_normalized.tsv` automatically from the accession mapping so the
ecology-aware step can still complete. Any genomes without legacy ecology labels will be marked
blank in that TSV until you curate them.

If you want ecology-aware prioritization around a specific label, set `FOCUS_ECOLOGY_LABEL`:

```bash
RUN_ECOLOGY_ANALYSIS=1 TARGET_GENOME=Your_Target_Genome_ID FOCUS_ECOLOGY_LABEL=Your_Ecology_Label bash summarize_clusterweave.sh
```

Stage and execute clinker panels directly when you want to restage or rerender them. By default this creates and runs a dataset-wide family atlas:

```bash
bash run_clinker.sh
```

Set `RUN_CLINKER=0` when you want to stage panel inputs and scripts without executing clinker:

```bash
RUN_CLINKER=0 bash run_clinker.sh
```

If you want targeted synteny around one genome of interest, set `TARGET_GENOME`:

```bash
TARGET_GENOME=Your_Target_Genome_ID bash run_clinker.sh
```

If you want atlas-only or targeted-only behavior explicitly, set `CLINKER_MODE`:

```bash
CLINKER_MODE=atlas bash run_clinker.sh
CLINKER_MODE=targeted TARGET_GENOME=Your_Target_Genome_ID bash run_clinker.sh
CLINKER_MODE=both TARGET_GENOME=Your_Target_Genome_ID bash run_clinker.sh
```

Optionally render summary figures from the generated tables:

```bash
bash run_figures.sh
```

`run_figures.sh` uses `Rscript` and will also try common Windows `Rscript.exe` locations from Bash/WSL. If needed, set `R_BIN` explicitly.

The figure layer is driven by the condensed BGC categories used in the summary tables:

- `NRP`
- `PKS`
- `RiPP`
- `Terpene`
- `Hybrid`
- `Other`

Isolated labels such as `indole`, `alkaloid`, `saccharide`, `ICS`, and other non-core categories are grouped into `Other`, while terpene cyclases and terpene synthases are grouped under `Terpene`.

## Ecology Metadata

Ecology is optional in `ClusterWeave`. The main BGC outputs do not require it.

- The user-facing ecology TSV lives at `Data/Results/<project-name>/summary_tables/ecofun_metadata_normalized.tsv` once generated for a project.
- The static repo template is [config/metadata_template.tsv](config/metadata_template.tsv), and it is intentionally header-only.
- The generated project-local editable scaffold is `Data/Results/<project-name>/summary_tables/ecofun_metadata_template.tsv`.
- The key columns are `accession`, `genome_id_current`, `taxonomy_id`, `genome_size_mb`, `genome_id_original_if_different`, `ecofun_primary`, and `ecofun_secondary`.
- Leave ecology blank if you only want core BGC summaries.
- Set `RUN_ECOLOGY_ANALYSIS=1` only when you want ecology-aware grouping and ranking.

## Examples vs Tests

- `examples/example_project/` is for public-safe walkthrough material, small example bundles, or manuscript/release companion assets meant for humans to browse.
- `tests/` is for automated software validation and regression checks. It is not intended to represent a biological analysis project.

## Skipping Tools

The default behavior is beginner-friendly: if a required container or resource is missing, `ClusterWeave` will try to pull or download it automatically.

For stage 1 specifically, `run_annotation_and_detection.sh` now tries to:
- pull the official antiSMASH image automatically if `ANTISMASH_SIF` is missing
- build a repo-local FunBGCeX SIF in `Software/funbgcex/` if `FUNBGCEX_SIF` is missing
- use that local FunBGCeX SIF for both the detection run and the helper Python calls
- only use the local FunBGCeX Python bootstrap if you explicitly enable it as an advanced fallback

If you want a lighter run or only care about certain stages, disable stages from the wrapper instead of editing the scripts:

```bash
RUN_STAGE_BIGSCAPE=0 bash run_clusterweave.sh
RUN_STAGE_SUMMARY=0 bash run_clusterweave.sh
RUN_STAGE_ANNOTATION=0 RUN_STAGE_BIGSCAPE=1 RUN_STAGE_SUMMARY=1 bash run_clusterweave.sh
RUN_STAGE_CLINKER=0 bash run_clusterweave.sh
RUN_CLINKER=0 bash run_clusterweave.sh
```

## Container Publishing

This repository includes a GitHub Actions workflow to publish container images to GitHub Container Registry (GHCR):

- Workflow file: `.github/workflows/publish-ghcr.yml`
- Trigger: git tags matching `v*` (for example `v0.2.0`) and GitHub release publish events
- Manual trigger: `workflow_dispatch`

Published images:

- `ghcr.io/<owner>/clusterweave-web`
- `ghcr.io/<owner>/clusterweave-worker`

Tagged releases also publish `latest`. The end-user compose file defaults to that tag; set `CLUSTERWEAVE_IMAGE_TAG=v0.2.0` to pin a specific release.

The web and worker services share the same Docker build context but use separate Dockerfiles:

- `Dockerfile.web` builds the lightweight public web/API service.
- `Dockerfile.worker` builds the job worker with the canonical ClusterWeave shell entrypoints and helper scripts available under `/clusterweave`.

The worker now treats the web app as a controller around the canonical shell workflow instead of maintaining a second implementation of the scientific pipeline in the UI layer.
Long term, heavy stages such as BiG-SCAPE, clinker, and NPLinker can be split into dedicated worker images while keeping the web/API service as the controller and the canonical shell scripts as the source of truth.

Example release publish flow:

```bash
git tag v0.2.0
git push origin v0.2.0
```

After the workflow completes, pull with:

```bash
docker pull ghcr.io/<owner>/clusterweave-web:v0.2.0
docker pull ghcr.io/<owner>/clusterweave-worker:v0.2.0
```

Then run the published web and worker images together using the end-user compose file:

```bash
docker compose -f clusterweave.yml up -d
```

Useful follow-ups:

```bash
docker compose -f clusterweave.yml logs -f
docker compose -f clusterweave.yml down
```

You can also run individual stages directly:

```bash
bash run_annotation_and_detection.sh
bash run_bigscape.sh
bash summarize_clusterweave.sh
RUN_ECOLOGY_ANALYSIS=1 TARGET_GENOME=Your_Target_Genome_ID bash summarize_clusterweave.sh
TARGET_GENOME=Your_Target_Genome_ID bash run_clinker.sh
CLINKER_MODE=atlas bash run_clinker.sh
CLINKER_MODE=targeted TARGET_GENOME=Your_Target_Genome_ID bash run_clinker.sh
```

For reproducibility-focused or offline use, switch the auto-fetch toggles back off in your env file:

```bash
AUTO_PULL_IMAGES=never
AUTO_BUILD_FUNBGCEX_SIF=0
AUTO_PULL_BIGSCAPE_SIF=0
AUTO_DOWNLOAD_PFAM=0
AUTO_DOWNLOAD_FASTTREE=0
MIBIG_AUTO_DOWNLOAD=0
AUTO_PULL_NPLINKER_SIF=0
NPLINKER_BOOTSTRAP_ENV=0
```

## Public-Release Notes

- `ClusterWeave` is currently a Linux/WSL-oriented Bash workflow.
- Container and network-backed modules are configured to auto-fetch or auto-build missing assets by default so a fresh clone is easier to run.
- The repository license covers `ClusterWeave` source files and build recipes only. Pulled images, SIFs, databases, and other third-party artifacts remain under their upstream terms and are intentionally not committed here.
- For the current third-party matrix, citations, and redistribution caveats, especially the separate GeneMark restriction that affects the BRAKER path, see [THIRD_PARTY.md](THIRD_PARTY.md).
- The first FunBGCeX-enabled run can take a while because `ClusterWeave` builds `Software/funbgcex/funbgcex_bundle.sif` locally.
- The canonical wrapper now carries the run through clinker staging automatically unless `RUN_STAGE_CLINKER=0`.
- The default clinker behavior is atlas-first across the whole dataset; set `TARGET_GENOME` to add targeted priority and shared-family panels.
- Clinker HTML panels now open with readability-first defaults: scale factor `12`, vertical spacing `70`, hidden locus coordinates, visible gene labels, similarity-group colors, and visible link labels.
- NPLinker remains exploratory as an evidence layer for putative product claims. Project submission to the Paired Omics Data Platform (PODP) is required to utilize this workflow.
- Ecology prioritization is optional and user-configurable through `RUN_ECOLOGY_ANALYSIS`, `ECOLOGY_FIELD`, and `FOCUS_ECOLOGY_LABEL`.
- `run_clusterweave.sh` writes a small provenance bundle under `Data/Results/<project-name>/reproducibility/`.
- Canonical runs also write `reproducibility/external_artifacts.tsv`, a checksum manifest for local SIFs, Pfam, FastTree, MiBIG, and other runtime artifacts.
- For a stricter manuscript-style rerun of the smoke project, source `profiles/release_v0.1.0.env` before running `run_clusterweave.sh`; it disables automatic artifact fetching and relies on prepopulated, checksum-comparable local artifacts.

## Included Release Metadata

- [LICENSE](LICENSE)
- [CITATION.cff](CITATION.cff)
- [THIRD_PARTY.md](THIRD_PARTY.md)
- [DATA_SOURCES.md](DATA_SOURCES.md)
- [BEGINNER_SETUP.md](BEGINNER_SETUP.md)

## Status

This repository is nearly-ready for a first public commit, but before journal submission or a production GitHub release I still need to review:

- authorship and citation metadata (.cff)
- final license choice (BSD, MIT, etc.)
- ANAQUA -> OSTI -> Resolution for compliance
- third-party redistribution terms (verified, potential counsel)
