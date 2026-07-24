# Web runtime

ClusterWeave remains a shell-first workflow. The standard-library web/API
service validates and stages inputs, the filesystem job store publishes bounded
queue metadata, one worker/admission layer claims a job, and
`web/canonical_pipeline.py` invokes the canonical shell entrypoints. Focused
Python helpers transform or render declared outputs. The shipped runtime does
not contain a second scientific implementation.

Project-hosted access is **coming soon**. Version 1.0.1 can be run locally or
through a separately administered institutional deployment.

## Shipped execution profiles

### Trusted single-user local profile

`docker-compose.yml` uses `CLUSTERWEAVE_RUNTIME_MODE=lab-docker` and
`ENGINE=docker`. Its worker contains the pinned Docker 29.6.1 CLI, mounts the
host Docker socket, and launches sibling scientific-tool containers with the
same named volumes at the same in-container paths:

- `clusterweave_job_data` at `/data`;
- `clusterweave_antismash_db` at `/databases/antismash`;
- `clusterweave_pfam_db` at `/databases/pfam`.

This profile lets the browser run the canonical workflow without installing the
scientific tools directly on the host. It is a trusted local convenience, not a
public isolation boundary.

The worker processes one job at a time by default. `WORKER_CONCURRENCY` is an
upper bound rather than a promise to start that many jobs: aggregate admission
also reserves CPU and estimated memory for every active job and can hold queued
work until capacity returns. Each job has an isolated `/data/jobs/<job-id>`
workspace, while `/data/software` and the database volumes are shared caches.

The initialized profile gives the worker 4 CPUs and 16 GiB. It also writes
`CLUSTERWEAVE_MAX_CPUS_PER_JOB=4`, so the local web service cannot accept a
public job above the default `CLUSTERWEAVE_WORKER_CPU_LIMIT=4`. Keep
`CLUSTERWEAVE_MAX_CPUS_PER_JOB` at or below the worker limit. A deliberate
larger installation must also reconcile `PIPELINE_CPUS`, `WORKER_CPU_BUDGET`,
worker memory, process limits, disk floors, and measured stage behavior.

Current Docker paths use the same shell scripts as direct runs:

- `run_annotation_and_detection.sh` handles fungal/bacterial preparation,
  antiSMASH, fungal FunBGCeX, and optional annotation fallbacks. Successful
  antiSMASH shards are compacted during the per-genome run.
- `run_bigscape.sh` uses `BIGSCAPE_DOCKER_IMAGE` when `ENGINE=docker`.
- `run_clinker.sh` can run the pinned clinker image and passes the Docker volume
  settings into the generated panel commands.
- `run_nplinker.sh` can use its pinned Python base and persistent environment.
- `run_figures.sh` renders the BGC overlap, taxon-specific multipanel,
  taxonomy/BGC/GCF, and graph-ready outputs.
- `run_phylogeny.sh` is an optional, bounded sequence-inference follow-up using
  a prebuilt runtime; it never installs or pulls tools from a job.

### Socket-free external executor profile

`clusterweave.yml` uses `CLUSTERWEAVE_RUNTIME_MODE=public-queue` with the Docker
socket disabled. It requires an external executor and reports unavailable
required stages through `/api/system/status` when that executor or a prepared
runtime is missing. The API rejects a job that requests an unavailable required
stage.

The shipped scheduler backend uses `CLUSTERWEAVE_EXECUTOR=slurm`. The submitter
claims the same filesystem queue records, writes an sbatch script under the job
workspace, submits with `sbatch --parsable`, records scheduler metadata, polls
`squeue` and `sacct`, and uses `scancel` for an administrator cancellation. A
compute node runs one job with `web/worker.py --once`, which invokes the same
canonical pipeline and shell stages. The current environment, shared-storage,
Apptainer/Singularity, and preflight contract is documented in
[CADES_SLURM_BACKEND.md](CADES_SLURM_BACKEND.md).

## Bounded resource planning

ClusterWeave enforces two independent resource boundaries:

1. The per-job planner fits whole-genome lanes, funannotate/BRAKER CPUs,
   FunBGCeX workers, antiSMASH record shards, and the legacy single-record path
   inside the accepted job CPU budget. Public targets are read from
   `CLUSTERWEAVE_PUBLIC_GENOME_PARALLELISM`,
   `CLUSTERWEAVE_PUBLIC_ANTISMASH_RECORD_PARALLELISM`,
   `CLUSTERWEAVE_PUBLIC_FUNANNOTATE_CPUS_PER_GENOME`, and
   `CLUSTERWEAVE_PUBLIC_FUNBGCEX_WORKERS_PER_GENOME`, then clamped as one plan.
2. Worker admission starts a job only when active CPU reservations and estimated
   memory reservations fit `WORKER_CPU_BUDGET` and
   `WORKER_MEMORY_BUDGET_MB`. `WORKER_MIN_FREE_DISK_GB` can hold work before the
   job filesystem reaches its floor, while `CLUSTERWEAVE_MIN_FREE_DISK_GB`
   applies at submission time.

Queue publication is atomic. The worker republishes sufficiently old pending
metadata after a web-process interruption, with a grace window that avoids
racing a live submission. A malformed queue record is quarantined. A job that
cannot fit the worker's total CPU or memory budget fails with a scheduling
explanation, so one impossible record cannot block later FIFO work indefinitely.

`PIPELINE_RESOURCE_MODE=conservative` is the portable default. It starts from
explicit settings and reduces a stage shape that would exceed the declared job
CPU budget. `PIPELINE_RESOURCE_MODE=auto` is an operator opt-in that derives and
freezes one bounded plan from the available CPU and memory limits. Auto mode does
not expand a running job or bypass worker admission.

Funannotate remains a whole-assembly operation because its training, evidence
integration, reconciliation, and locus assignment are genome-wide. The safe CPU
relationship is `GENOME_PARALLELISM * ANNO_CPUS <= CPUS`. Throughput comes from
independent whole-genome lanes and native funannotate CPUs, not record-level
reassembly that could change biological output and identifiers.

The memory estimator uses configurable base, per-genome, antiSMASH-shard,
annotation-CPU, FunBGCeX-worker, and optional-phylogeny terms, then applies a
safety factor and minimum. The corresponding `WORKER_MEMORY_*` settings are
operator calibration inputs, not scientific parallelism controls. Compose also
sets common numerical thread variables to one, bounds the worker process tree,
and can apply hard CPU, memory, and process ceilings to Docker tool children.

## Taxonomy figure and optional sequence phylogeny

`/api/system/status` reports `taxon_tree_figure` and `sequence_phylogeny`
separately. The normal taxonomy/BGC/GCF renderer needs only the worker Python
environment and writes a static SVG, data bundle, Newick, tables, and GraphML.
Optional PNG export may use CairoSVG, but the core bundle does not require a
sequence-inference runtime.

Sequence phylogeny becomes available only when preflight can inspect an
already-built Docker image or a pinned SIF. The portable defaults keep
`RUN_PHYLOGENY=0`, `PHYLOGENY_REQUIRED=0`, `PHYLOGENY_CPUS=1`,
`PHYLOGENY_PARALLELISM=1`, and `RUN_CROSS_KINGDOM_EVIDENCE=0`. Submit-token jobs
cannot enable sequence inference or cross-kingdom evidence; administrator
authorization is required.

A requested sequence run prepares only bounded families from shortlisted
cross-domain GCF regions and matching antiSMASH annotations. It does not perform
sequence-similarity clustering or download a runtime. Computational tree or GCF
context does not establish an evolutionary event, mechanism, or direction. A
missing optional result does not invalidate the core taxonomy/BGC/GCF workflow
unless an operator explicitly set the optional stage as required.

## Capacity, uploads, and retention

A concurrency value is not a queue-size setting. Operators must measure
aggregate CPU, memory, process, and disk reservations on representative fungal,
bacterial, and mixed jobs before increasing active work. The portable local
profile deliberately begins with one job, one genome/record lane, a four-CPU
worker, and no retained raw shard work.

Streaming shard compaction reduces temporary antiSMASH growth but does not
replace retention planning. Final antiSMASH regions, FunBGCeX outputs,
annotation products, BiG-SCAPE data, figures, uploads, and packages remain
per-job data. Monitor the filesystem mounted at `/data`, set both disk floors,
and export or back up declared results before cleanup.

Multipart uploads are spooled under `/data/.upload_staging`, copied and
validated in bounded chunks, rejected from `Content-Length` before parsing when
the configured total plus form overhead is too large, and limited by
`CLUSTERWEAVE_MAX_CONCURRENT_UPLOADS` (two by default). Retention sweeping
applies only to terminal `success` or `failed` jobs; queued and running work is
not removed solely because it is old.

## Interactive metadata and operator logs

The administrator job drawer reads bounded `job_summary.v1.json` records rather
than loading each full `job.json`. Selecting a job loads metadata and the
declared result index, while opening the QA Console requests the newest bounded
log page. Earlier pages are fetched explicitly. Existing administrator and
per-job authorization still controls those reads.

Completed runs write a private, HMAC-signed result index beside the public
manifest. The completion path has verified and hashed the manifest contents, so
interactive file-list requests validate the signed index and manifest identity.
Direct downloads retain their digest check, family allowlists, path containment,
and private/raw BiG-SCAPE database policy. Keep
`CLUSTERWEAVE_JOB_TOKEN_SECRET` stable because it signs result access and the
completion indexes.

At completion, ClusterWeave builds the full workbench ZIP once. It calculates
the ZIP's SHA-256 checksum and records the ZIP's stable filesystem identity in
the signed result index. An authenticated request can therefore stream the
unchanged ZIP directly. If the package belongs to a legacy job, is missing, or
has changed, ClusterWeave rebuilds it from the signed public manifest instead of
trusting the stored file. This behavior avoids repeated compression of large
antiSMASH and BiG-SCAPE outputs, although transfer time still depends on the
package size and the available network bandwidth.

After upgrading an installation with legacy jobs, an operator may run
`python3 bin/backfill_result_attestations.py` in the web service environment. It
writes bounded summaries and hashes terminal manifests once. Run it outside
interactive request handling with the same data volume and stable secret as the
web service.

## Opaque public result delivery

New jobs receive a random 128-bit `public_run_id`; legacy jobs receive a stable
HMAC alias, and every artifact ID is generation-bound. Browser result actions
use opaque result and artifact routes. Public JSON and links do not contain the
private worker-directory ID or a storage-relative path. In public mode, legacy
internal-ID file, archive, and viewer routes are administrator-only.

A read token is a bearer capability delivered in the initial URL fragment,
removed from browser history, and retained only in session storage. Generated
antiSMASH and FunBGCeX HTML is fetched through opaque artifact routes and runs
only in the existing scripts-only opaque-origin sandbox. HTTPS is required for a
hosted deployment to protect tokens and result bytes in transit; TLS termination
is outside this application-layer runtime.

## Evidence workbench package

An investigator may need the underlying sequence records after reviewing the
interactive summaries. Therefore, the authenticated full package retains the
following sequence-bearing files:

- `input_gbks/<genome>.gbk` is the staged genome used by the downstream
  analysis. For a bacterial genome, this is the retained feature-free GenBank
  file prepared for antiSMASH and Prodigal.
- `antismash/<genome>/*region<number>.gbk` contains the final antiSMASH region
  records.
- `funbgcex/<genome>/results/*.funbgcex_results/BGCs/*.gbk` contains the
  canonical FunBGCeX BGC records. ClusterWeave omits the duplicate
  `all_clusters` copy.
- `evidence/clusterweave_evidence_manifest.tsv` records the portable path,
  evidence role, genome and taxon labels, public source accession when present,
  byte count, and SHA-256 checksum for each included evidence file.

The package omits original upload objects, NCBI download caches, private job
metadata, tokens, commands, environment files, logs, scratch files, database
caches, and operator paths. However, the package does contain genome and BGC
sequences. Operators and investigators should therefore protect its result
link according to the sensitivity of the submitted genomes.

## Security and access rules

- Keep `docker-compose.yml` bound to loopback because its worker mounts
  `/var/run/docker.sock`. Never expose that profile as an unaudited service.
- The socket-free `clusterweave.yml` profile requires a configured external
  executor and pre-prepared runtimes. It does not silently fall back to the host
  Docker socket.
- Rebuild or recreate services without deleting named volumes. Never run
  `docker compose down -v` during an upgrade unless permanent deletion is the
  explicit, reviewed intent.
- Failed or completed jobs can be re-queued with selected stages in the same
  workspace, preserving completed expensive stages unless an administrator
  requests a forced rerun.
- In `CLUSTERWEAVE_PUBLIC_MODE=1`, submission is open only according to
  `CLUSTERWEAVE_SUBMISSIONS_OPEN` and the optional submit-token policy. Job
  lists, reruns, deletes, full telemetry, raw logs, and legacy internal-ID file
  routes require administrator credentials. Opaque results require the per-job
  read token or administrator credential.
- Prefer SHA-256 token inputs for app-side verification. Plaintext submit and
  administrator environment variables remain compatibility inputs, but secrets
  must stay outside source and browser-visible state.
- Anonymous `/api/system/status` is redacted to service state, submission state,
  and aggregate completed work. Detailed queue, capability, job, and worker
  information is private.
- Public-mode CORS is not a wildcard. Configure
  `CLUSTERWEAVE_ALLOWED_ORIGINS` only for reviewed browser origins.
- Public uploads are limited to one-accession-per-line `.txt`, bounded FASTA or
  GenBank genomes, and the UI-generated normalized ecology table when that mode
  is enabled. Generic archives, arbitrary environment overrides, and public
  NPLinker settings are rejected.
- Canonical quotas include 50 NCBI accessions and 50 uploaded genome files.
  `CLUSTERWEAVE_MAX_CPUS_PER_JOB` clamps all CPU-related request fields; in the
  initialized local profile its value is 4.
- Terminal jobs receive a retention deadline (30 days by default). Optional
  completion email is enabled only through the SMTP settings and sends a private
  fragment result link. Hosted links require a reviewed HTTPS base URL.
- `python3 web/maintenance.py sweep-expired-jobs` removes expired terminal job
  data and retains only aggregate deletion counters. A never-expire policy
  requires the explicit allow setting and operator documentation.
