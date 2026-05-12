# Web Runtime Strategy

ClusterWeave remains a shell-first workflow. The web/API layer stages inputs and owns job orchestration, but the scientific stages still run through the canonical scripts.

## Runtime Slices

### Short Term: Lab QA Bridge

The dev/lab compose file (`docker-compose.yml`) uses `CLUSTERWEAVE_RUNTIME_MODE=lab-docker` and `ENGINE=docker`. In this mode the worker mounts the host Docker socket and launches stage containers with named Docker volumes mounted back at the same in-container paths:

- `clusterweave_job_data` -> `/data`
- `clusterweave_antismash_db` -> `/databases/antismash`
- `clusterweave_pfam_db` -> `/databases/pfam`

This is intentionally a lab convenience. It lets the current web UI run the canonical scripts without installing Apptainer inside the worker container.

The worker processes one job at a time by default. For lab machines with enough CPU, memory, and disk I/O, set `WORKER_CONCURRENCY=2` or higher before starting compose. Each job still keeps an isolated `/data/jobs/<job-id>` workspace, but shared caches under `/data/software` and database volumes are common to all jobs.

Current Docker-native bridge paths:

- `run_annotation_and_detection.sh`: uses local worker antiSMASH when present and a repo-built `clusterweave-funbgcex:latest` Docker image for FunBGCeX; optional funannotate/BRAKER fallbacks can run via Docker images when enabled.
- `run_bigscape.sh`: supports `ENGINE=docker` with `BIGSCAPE_DOCKER_IMAGE`.
- `run_clinker.sh`: supports `CLINKER_USE_DOCKER_IMAGE=1` and passes Docker settings into generated panel scripts.
- `run_nplinker.sh`: supports `ENGINE=docker` with a Python base image and a persistent `/data/software/nplinker` venv.
- `run_figures.sh`: the worker image includes base R for summary SVG rendering; if Rscript is unavailable in another runtime, the wrapper skips only the R summary figure and still attempts the Python BiG-SCAPE network SVG.

HPC/Singularity behavior remains the default when `ENGINE` is unset and Singularity/Apptainer is available.

### Long Term: Public Hosted Runtime

Public hosting should not expose the host Docker socket to a web-facing worker. The target model is:

- web/API service accepts uploads, validates settings, and owns the job DAG
- queue stores stage-ready work items and state transitions
- stage-specific workers run prebuilt, constrained images
- workers receive declared inputs and write declared outputs only
- downstream tool containers never launch sibling containers themselves

The published compose file (`clusterweave.yml`) is deliberately socket-free. It surfaces unavailable stages through `/api/system/status`; the UI disables those stages and the API rejects jobs that request them.

## Stage DAG Boundary

| Stage | Depends On | Declared Inputs | Declared Outputs | Key Knobs |
| --- | --- | --- | --- | --- |
| prepare | uploads | accession list, optional NCBI CLI cache | `Data/Genomes/Fungi/<project>` | `ACCESSIONS_FILE`, `RUN_GENOME_PREP` |
| annotation/FunBGCeX | prepare or uploaded genomes | FASTA/GenBank files | `antismash/`, `funbgcex/`, staged GBKs, manifest | `CPUS`, `ANNO_CPUS`, `WORKERS`, `ANNOTATION_FALLBACK_ORDER`, `BRAKER3_ENABLED` |
| BiG-SCAPE | annotation | antiSMASH region GBKs, Pfam, optional MiBIG | `big_scape/` | `THREADS`, `AUTO_DOWNLOAD_PFAM`, `MIBIG_AUTO_DOWNLOAD`, `BIGSCAPE_*` |
| summarize/crosswalk | annotation, optional BiG-SCAPE | antiSMASH, FunBGCeX, BiG-SCAPE outputs, metadata | `summary/`, `summary_tables/` | `RUN_ECOLOGY_ANALYSIS`, `ECOLOGY_FIELD`, `FOCUS_ECOLOGY_LABEL` |
| clinker | summarize, optional BiG-SCAPE | shortlist tables, region GBKs, optional MiBIG | `clinker/` panel HTML/TSV/manifests | `CLINKER_MODE`, `PANEL_TARGET_SET`, `ATLAS_STAGE_LIMIT`, `RUN_CLINKER` |
| figures | summarize | summary tables | `figures/` | `FIGURES_REQUIRED`, `R_BIN` |
| NPLinker | annotation, BiG-SCAPE, GNPS/PODP inputs | target strain, antiSMASH, GNPS/PODP assets, strain mapping | `nplinker/` ranked link tables | `RUN_MODE`, `TARGET_STRAIN`, `PODP_ID`, `GNPS_VERSION` |

`web/canonical_pipeline.py` is the current bridge that prepares this layout and invokes `run_clusterweave.sh`. It is not the final DAG engine, but it now passes enough explicit runtime settings for each stage to be split out later.

## Safety Rules

- `docker-compose.yml` is dev/lab only because it mounts `/var/run/docker.sock`.
- `clusterweave.yml` is socket-free and should be the baseline for public demos.
- Public deployments should run prebuilt stage images through a queue worker model, not Docker-from-Docker.
- Runtime capabilities are reported through `/api/system/status`; the API rejects jobs requesting unavailable required stages.
- Failed or completed jobs can be re-queued in place with selected stages. This reuses the existing job workspace so expensive completed stages such as antiSMASH do not need to be repeated unless selected with force rerun.
- Public API hardening is opt-in with `CLUSTERWEAVE_PUBLIC_MODE=1`. In public mode, job creation requires `CLUSTERWEAVE_SUBMIT_TOKEN` or `CLUSTERWEAVE_ADMIN_TOKEN`; job list, rerun, delete, and full worker telemetry require `CLUSTERWEAVE_ADMIN_TOKEN`; job detail/log/file reads require the per-job read token returned at submission or the admin token.
- Per-job read tokens are random bearer tokens. The server stores only a digest derived from `CLUSTERWEAVE_JOB_TOKEN_SECRET`; keep that secret stable across web service restarts so result links remain valid.
- Anonymous public `/api/system/status` is redacted to service online/offline, submissions open/paused, and aggregate jobs processed. Full worker runtime, capabilities, queue details, logs, and job IDs are admin-only.
- Public-mode CORS no longer uses wildcard access. Set `CLUSTERWEAVE_ALLOWED_ORIGINS` to a comma-separated list of hosted browser origins when cross-origin API calls are required.
- Public-mode uploads are constrained to one-accession-per-line `.txt` files, genome files `.fasta`, `.fa`, `.fna`, `.fsa`, `.gb`, `.gbk`, `.gbff`, and the UI-generated `ecofun_metadata_normalized.tsv` only when ecology-aware analysis is enabled. TSV/CSV accession tables, auxiliary formats, generic archives, raw metadata paths, public NPLinker settings, and public raw environment overrides are rejected before worker execution.
- Public quotas are controlled by `CLUSTERWEAVE_MAX_ACCESSIONS`, `CLUSTERWEAVE_MAX_GENOME_FILES`, `CLUSTERWEAVE_MAX_UPLOAD_FILE_MB`, `CLUSTERWEAVE_MAX_UPLOAD_TOTAL_MB`, `CLUSTERWEAVE_MAX_QUEUED_JOBS`, and `CLUSTERWEAVE_MAX_CPUS_PER_JOB`. CPU-related request fields are clamped to the accepted CPU count.
- Job metadata includes `retention_days` and `expires_at`; when the worker marks a job `success` or `failed`, `completed_at` or `failed_at` is set and the expiration date is refreshed from that terminal timestamp. The default retention window is `CLUSTERWEAVE_JOB_RETENTION_DAYS=30`.
- Optional completion/failure email is enabled only with `CLUSTERWEAVE_SMTP_ENABLED=1`. The UI discovers this through redacted `/api/system/status`; email addresses are stored only in job metadata, and terminal notifications send a private fragment result link plus expiration date. Set `CLUSTERWEAVE_PUBLIC_BASE_URL` for hosted links and `CLUSTERWEAVE_SMTP_FROM` or `CLUSTERWEAVE_EMAIL_FROM` for the sender address.
- Expired jobs are removed with `python3 web/maintenance.py sweep-expired-jobs`. The sweeper deletes uploads, logs, work directories, result files, email metadata, and read-token hashes, then keeps only aggregate deletion counters under the data directory. `CLUSTERWEAVE_JOB_RETENTION_DAYS=0` or `never` requires `CLUSTERWEAVE_ALLOW_NEVER_EXPIRE_JOBS=1` and public admin documentation.
