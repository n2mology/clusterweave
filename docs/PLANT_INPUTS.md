# Supplied plant annotation

ClusterWeave can route translated green-plant GenBank records to the prepared
plantiSMASH 2.0.4 supplied-CDS profile. The plant route reuses supplied coding
sequences (CDS); it does not predict genes. `both` retains its historical meaning
of fungi plus bacteria. Use `plants` for plant inputs and `mixed` for a cohort
with individually validated fungal, bacterial or plant assignments.

New and reset input stations default to `mixed`; `both` is retained for saved
jobs and explicit CLI/API callers and is absent from new intake choices.
Taxonomy verification does not validate CDS or enable a plant predictor.

In the input station, choose the scope and upload translated GenBank (`.gbk`,
`.gb` or `.gbff`). A matching FASTA can accompany manual GenBank annotation;
record identifiers and nucleotide sequences must agree. The server inspects the
actual annotation. NCBI annotation availability remains pending until the
retrieved content is checked. Missing translations, incompatible annotation and
conflicting source taxonomy stop the plant route with an annotation-required or
validation message. Supply corrected, matching annotation before retrying.

FASTA+GFF3 is not a supported plant input: the existing conversion has not been
established to preserve all compound locations, strand, phase, partial features,
translations and isoforms. Original DNA and peptides remain unchanged. A declared
3-prime partial CDS with two known terminal bases is compatible only when all
four possible completions give the supplied peptide. Source-declared exceptions
remain distinguishable from exact translations and unexplained errors; they are
not independent biological validation.

## Command-line execution

Run the root scripts from the repository. Plant execution requires a validated
per-genome TSV route manifest with the same columns as
`summary_tables/genome_taxon_manifest.tsv`. Each plant row must use
`taxon_group=plants`, `prediction_method=existing_cds` (or the unresolved
`annotation_required` state), and `detector_profile=plantismash`. Place the supplied
GenBank at `PLANTS_GENOME_ROOT/<genome_id>.gbk`. The annotation runner checks its
content again before execution.

```bash
export ANALYSIS_SCOPE=plants
export GENOME_TAXON_MANIFEST=/path/to/validated-routes.tsv
export PLANTS_GENOME_ROOT=/path/to/annotated-plants
export PLANTISMASH_SIF=/path/to/prepared/plant.sif
export PLANTISMASH_ENGINE=apptainer
python3 bin/plantismash_runtime.py check
bash run_annotation_and_detection.sh
```

The command above runs detection only. For the complete comparison, summary and
synteny workflow, use a separate project directory with the standard
`data/results/<project-name>` layout. Keep the route manifest, plant input root,
runtime selection and prepared SIF settings from above, and prepare the other
required runtimes and reference data first:

```bash
export PROJECT_DIR="$PWD"
export PROJECTS_ROOT=/path/to/plant-project
export PROJECT_NAME=plant-run
export DATA_ROOT="$PROJECTS_ROOT/data"
export RESULTS_ROOT="$DATA_ROOT/results/$PROJECT_NAME"
export WORK_ROOT="$PROJECTS_ROOT/work"
export SOFTWARE_ROOT=/path/to/prepared-software
export PFAM_DIR=/path/to/prepared-pfam
export MIBIG_CACHE="$SOFTWARE_ROOT/big_scape/resources/mibig_cache"
export ENGINE=apptainer
export CLINKER_USE_DOCKER_IMAGE=0
export METADATA_TSV="$PROJECTS_ROOT/metadata.tsv"
mkdir -p "$PROJECTS_ROOT"
python3 bin/normalize_metadata.py \
  --genome-dir "$PLANTS_GENOME_ROOT" \
  --out "$METADATA_TSV" \
  --template-out "$PROJECTS_ROOT/metadata-template.tsv" \
  --allow-missing-legacy
bash run_clusterweave.sh --raw
```

Use an existing metadata TSV instead when available. A generated blank scaffold
identifies the input genomes; it does not infer ecology or biological traits.
The full workflow requires the prepared BiG-SCAPE, Pfam, clinker and configured
MIBiG assets described in [runtime preparation](CONFINED_SIF.md). A validated
zero-call plant run remains a successful empty detection: no BGC families or
multi-locus synteny are invented for it. A failed downstream stage still returns
a nonzero workflow exit, even when BGC detection succeeded.

Use the prepared runtime described in [plant runtime preparation](PLANTISMASH_RUNTIME.md).
That guide owns the dependency versions, source/profile pins and confinement
requirements. Jobs do not acquire or replace the runtime; the administrative
capability view reports whether it is ready.

## Results and downloads

A successful plant result includes an interactive plantiSMASH report, GenBank
and spreadsheet exports, cluster files and record mappings. The package places
these under `plantismash/<genome>/` and keeps the staged annotation once under
`input_gbks/`. The same report opens online and from the extracted package.
Candidate/family tables, figures and applicable clinker panels provide shared
views across the analysis.

A zero count means detection completed without finding clusters. Failed or
incomplete output and records without CDS are reported separately. BiG-SCAPE
may use fewer clusters or CDS features than the detector produced; see
[tool outputs and comparison selections](REPRODUCIBILITY.md#tool-outputs-and-comparison-selections).
Files converted for comparison retain their plantiSMASH origin and do not become
antiSMASH predictions.

The BiG-SCAPE heatmap needs at least two genomes and two families in the selected
view; smaller selections still have a family table and network. Portable clinker
packages include their inputs and `run_panel.sh`, which uses a prepared clinker
0.0.32 runtime. Similar clusters or shared families do not establish horizontal
gene transfer or biological accuracy.

## Dependency notices

ClusterWeave's adapter code uses the repository BSD 3-Clause license.
plantiSMASH's supplied runtime carries the GNU Affero General Public License v3;
its corresponding source, modifications and third-party notices remain part of
the separately prepared runtime distribution. This repository does not bundle the
SIF. Funannotate2 and Tiberius are not supported annotation routes. Runtime redistribution and hosted-use
clearance are separate from local functional verification.

The web image copies the existing Biopython 1.81 and NumPy 2.2.5 reader dependencies
from the prepared antiSMASH base, including their distribution metadata and
license texts. Clinker remains a separately prepared runtime. Cite the actual
tools used in the generated report; plantiSMASH is cited as
[Kautsar et al., 2017](https://doi.org/10.1093/nar/gkx305).

## Resource allocation and progress

The root `run_annotation_and_detection.sh` remains the stage orchestrator.
New hosted runs target up to two genome lanes and two antiSMASH record shards
per lane. The shared planner bounds their product by the job CPU allocation and
uses the active worker's memory formula and total admission budget to reduce
fan-out when needed. Aggregate worker admission still gates queued jobs; a
minimal request that cannot fit fails with its resource reason. Explicit operator
targets of one and the frozen settings of existing jobs retain serial behavior.

For CLI use, `PIPELINE_RESOURCE_MODE=auto` selects bounded CPU and memory targets;
`CPUS` and `PIPELINE_MEMORY_BUDGET_MB` can restrict that allocation. The same
memory estimator now checks record fan-out as well as genome lanes. Conservative
CLI mode preserves explicit settings such as `GENOME_PARALLELISM=1`,
`ANTISMASH_RECORD_PARALLELISM=2`, `ANTISMASH_SHARD_CPUS=2`, `CPUS=4`.
These are a whole-job four-CPU allocation, not four CPUs per shard. Memory and
storage must also fit; increasing worker concurrency does not accelerate a shard.
Record selection, merge order and tool arguments are unchanged.

antiSMASH receives a separate writable job scratch/cache directory per confined
invocation. A recoverable Matplotlib cache warning remains a warning in progress;
a nonzero exit, traceback or invalid output remains a failure. Raw diagnostics
are retained. The web service provides the modified plantiSMASH source archive at
`/assets/third-party/plantismash-source.zip`; see the
[component notices](../THIRD_PARTY.md#pinned-supplied-cds-plantismash-source-build)
for its contents and source requirements.
