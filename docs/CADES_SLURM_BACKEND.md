# CADES Slurm backend

This document describes the shipped scheduler-backed ClusterWeave executor
for a CADES or comparable Slurm environment. It keeps the web API, result
tokens, retention policy, administrator dashboard, canonical shell workflow,
and filesystem queue. Slurm supplies execution and does not replace the queue
with a database or broker.

## Shipped architecture

ClusterWeave still creates jobs the same way:

- `/data/jobs/<job-id>/job.json`
- `/data/jobs/<job-id>/inputs/`
- `/data/queue/<job-id>.json`

The execution backend is selected by `CLUSTERWEAVE_EXECUTOR`:

- `CLUSTERWEAVE_EXECUTOR=local` is the default and keeps the existing polling worker behavior.
- `CLUSTERWEAVE_EXECUTOR=slurm` starts a scheduler submitter instead of running scientific work in the worker loop.

In Slurm mode, the submitter claims queue files with the same filesystem rename pattern as the local worker, writes scheduler files under `/data/jobs/<job-id>/slurm/`, submits with `sbatch --parsable`, records `slurm_job_id` and scheduler metadata in `job.json`, polls `squeue` and `sacct`, and calls `scancel` when an admin cancellation marker appears.

The compute job runs exactly one ClusterWeave job:

```bash
python3 web/worker.py --once <job-id> --queue-payload /data/jobs/<job-id>/slurm/queue_payload.json
```

The one-shot worker runs the existing canonical pipeline and exits. It does not poll the queue.

## Required CADES values

Fill these in from approved CADES/project policy. Do not commit real usernames, allocation IDs, hostnames, private paths, SSH keys, or tokens.

```bash
CLUSTERWEAVE_EXECUTOR=slurm
CLUSTERWEAVE_SLURM_ACCOUNT=<CADES_ACCOUNT_OR_ALLOCATION>
CLUSTERWEAVE_SLURM_PARTITION=<CADES_PARTITION>
CLUSTERWEAVE_SLURM_QOS=<CADES_QOS_OR_EMPTY>
CLUSTERWEAVE_SLURM_TIME=04:00:00
CLUSTERWEAVE_SLURM_MEM=16G
CLUSTERWEAVE_SLURM_NODES=1
CLUSTERWEAVE_SLURM_CPUS_PER_TASK=4
CLUSTERWEAVE_SLURM_MAX_SUBMITTED=2
CLUSTERWEAVE_SLURM_WORKDIR=<SHARED_WORKDIR_VISIBLE_TO_LOGIN_AND_COMPUTE_NODES>
CLUSTERWEAVE_SLURM_PROLOGUE=<MODULE_LOADS_OR_ENV_SETUP>
CLUSTERWEAVE_SLURM_PYTHON=python3
ENGINE=apptainer
```

Use `ENGINE=singularity` only when that is the supported runtime on the target nodes.

Discover allocation values with:

```bash
sacctmgr -n -P show assoc user="$USER" format=Account,Partition,QOS%30,DefaultQOS%30
```

Use only accounts, partitions, and QOS values approved for the deployment. Some CADES partitions require `#SBATCH --nodes`; the backend emits `CLUSTERWEAVE_SLURM_NODES=1` by default.

## Example environment file

This example uses placeholders only.

```bash
DATA_DIR=<SHARED_CLUSTERWEAVE_DATA_DIR>
CLUSTERWEAVE_ROOT=<SHARED_CLUSTERWEAVE_REPO_DIR>
CLUSTERWEAVE_SOFTWARE_ROOT=<SHARED_CLUSTERWEAVE_SOFTWARE_CACHE_DIR>

CLUSTERWEAVE_EXECUTOR=slurm
CLUSTERWEAVE_SLURM_ACCOUNT=<CADES_ACCOUNT_OR_ALLOCATION>
CLUSTERWEAVE_SLURM_PARTITION=<CADES_PARTITION>
CLUSTERWEAVE_SLURM_QOS=<CADES_QOS_OR_EMPTY>
CLUSTERWEAVE_SLURM_TIME=04:00:00
CLUSTERWEAVE_SLURM_MEM=16G
CLUSTERWEAVE_SLURM_NODES=1
CLUSTERWEAVE_SLURM_CPUS_PER_TASK=4
CLUSTERWEAVE_SLURM_MAX_SUBMITTED=1
CLUSTERWEAVE_SLURM_WORKDIR=<SHARED_CLUSTERWEAVE_DATA_DIR>
CLUSTERWEAVE_SLURM_PROLOGUE='module purge
module load <PYTHON_MODULE>'
CLUSTERWEAVE_SLURM_PYTHON=python3
ENGINE=apptainer
CLUSTERWEAVE_CONTAINER_ENGINE=apptainer

APPTAINER_CACHEDIR=<SHARED_APPTAINER_CACHE_DIR>
SINGULARITY_CACHEDIR=<SHARED_APPTAINER_CACHE_DIR>

CLUSTERWEAVE_PUBLIC_MODE=1
CLUSTERWEAVE_SUBMISSIONS_OPEN=1
CLUSTERWEAVE_SUBMIT_TOKEN=<INVITE_CODE>
CLUSTERWEAVE_ADMIN_TOKEN=<PRIVATE_ADMIN_TOKEN>
CLUSTERWEAVE_JOB_TOKEN_SECRET=<STABLE_RANDOM_SECRET>
```

Keep the real file outside version control or in a managed secret store.

For production-like Slurm runs, pre-stage SIFs and disable job-time pulls:

```bash
AUTO_PULL_IMAGES=never
AUTO_BUILD_FUNBGCEX_SIF=0
AUTO_PULL_BIGSCAPE_SIF=0
AUTO_PULL_NPLINKER_SIF=0
AUTO_DOWNLOAD_PFAM=0
AUTO_DOWNLOAD_FASTTREE=0
MIBIG_AUTO_DOWNLOAD=0
```

Use `/home` only for tiny smoke tests unless CADES confirms the quota and policy are appropriate. Real jobs should place `DATA_DIR`, `CLUSTERWEAVE_SOFTWARE_ROOT`, and container caches on approved shared storage visible from both login and compute nodes.

## Dry-run script-generation test

This test does not call a real Slurm scheduler. It injects fake `sbatch`, `squeue`, `sacct`, and `scancel` responses.

```bash
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest tests.test_slurm_backend
```

The test verifies sbatch script generation, Slurm state parsing, job metadata updates, and cancellation metadata.

## CADES preflight checks

Run these checks before submitting real jobs:

```bash
which sbatch squeue sacct scancel
command -v apptainer singularity
apptainer --version
squeue -u "$USER"
```

Check approved shared storage with a timeout so a stuck mount does not hang the shell:

```bash
timeout 10s stat -c '%A %U %G %n' <APPROVED_SHARED_CLUSTERWEAVE_ROOT>
```

If shared scratch is missing or times out, keep only tiny smoke tests in a temporary home-backed smoke directory and resolve storage with CADES support before real scientific runs.

Apptainer registry conversion can be tested with a tiny image:

```bash
mkdir -p "$CLUSTERWEAVE_SOFTWARE_ROOT/smoke"
apptainer pull --force "$CLUSTERWEAVE_SOFTWARE_ROOT/smoke/alpine_latest.sif" docker://alpine:latest
apptainer exec "$CLUSTERWEAVE_SOFTWARE_ROOT/smoke/alpine_latest.sif" sh -lc 'echo apptainer_ok; uname -a'
```

This verifies registry access and SIF creation. It does not prove large tool images or compute-node outbound network access, so pre-stage real tool SIFs before public jobs.

Validate Apptainer on a compute node with a tiny Slurm job before staging real tool images. The job should use the same account, partition, QOS, scratch-backed cache, and software root planned for ClusterWeave:

```bash
SMOKE_ROOT="<SHARED_CLUSTERWEAVE_ROOT>/apptainer_compute_smoke"
mkdir -p "$SMOKE_ROOT" "$CLUSTERWEAVE_SOFTWARE_ROOT/smoke" "$APPTAINER_CACHEDIR"

cat > "$SMOKE_ROOT/apptainer_compute.sbatch" <<EOF
#!/usr/bin/env bash
#SBATCH --job-name=cw-apptainer-smoke
#SBATCH --account=$CLUSTERWEAVE_SLURM_ACCOUNT
#SBATCH --partition=$CLUSTERWEAVE_SLURM_PARTITION
#SBATCH --qos=$CLUSTERWEAVE_SLURM_QOS
#SBATCH --nodes=1
#SBATCH --cpus-per-task=1
#SBATCH --mem=2G
#SBATCH --time=00:10:00
#SBATCH --chdir=<SHARED_CLUSTERWEAVE_ROOT>
#SBATCH --output=$SMOKE_ROOT/apptainer_compute_%j.out
#SBATCH --error=$SMOKE_ROOT/apptainer_compute_%j.err

set -euo pipefail
export APPTAINER_CACHEDIR=$APPTAINER_CACHEDIR
export SINGULARITY_CACHEDIR=$APPTAINER_CACHEDIR

SIF="$CLUSTERWEAVE_SOFTWARE_ROOT/smoke/alpine_compute.sif"
mkdir -p "\$(dirname "\$SIF")" "\$APPTAINER_CACHEDIR"
hostname -f
apptainer --version
apptainer pull --force "\$SIF" docker://alpine:latest
apptainer exec "\$SIF" sh -lc 'echo apptainer_compute_ok; uname -a; head -5 /etc/os-release'
EOF

sbatch --parsable "$SMOKE_ROOT/apptainer_compute.sbatch"
```

After the job leaves `squeue`, confirm `sacct` reports `COMPLETED|0:0`, stdout contains `apptainer_compute_ok`, and the SIF exists under `CLUSTERWEAVE_SOFTWARE_ROOT/smoke/`. Warnings about unsupported xattrs can be harmless on scratch filesystems when the SIF is created and executes successfully.

## Small Slurm smoke tests

Run a real Slurm smoke test only after the operator confirms site access, allocation, filesystem, and queue policy.

1. Use a shared `DATA_DIR`, `CLUSTERWEAVE_ROOT`, and `CLUSTERWEAVE_SOFTWARE_ROOT` visible to login and compute nodes.
2. Set `CLUSTERWEAVE_SLURM_MAX_SUBMITTED=1`, a short walltime, and conservative memory.
3. Start the web service normally.
4. Start the worker submitter on the login/service node:

```bash
CLUSTERWEAVE_EXECUTOR=slurm python3 web/worker.py
```

5. Submit one tiny test job through the UI or API.
6. Confirm `job.json` records `executor=slurm`, `slurm_job_id`, and `scheduler.kind=slurm`.
7. Watch scheduler status with `squeue` and `sacct`.
8. Watch ClusterWeave logs under `/data/jobs/<job-id>/logs.txt`.
9. Test admin delete/cancel on a disposable job and confirm `scancel` is issued.

For a controlled smoke outside the web UI, create a disposable job and submit only one queue claim:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, "web")
from worker import claim_next_job
from slurm_backend import SlurmBackend

backend = SlurmBackend(claim_next_job=claim_next_job)
print("submitted", backend.submit_waiting_claims())
PY
```

After the job leaves `squeue`, refresh scheduler metadata:

```bash
python3 - <<'PY'
import sys
sys.path.insert(0, "web")
from slurm_backend import SlurmBackend
print(SlurmBackend().poll_once())
PY
```

Recommended smoke sequence:

- No-input failure smoke: submit a job with all heavy stages disabled and no genome input. Expected result is ClusterWeave `failed` with a clear "No genome inputs were staged" error, plus final Slurm state captured from `sacct`.
- Tiny FASTA success smoke: add one small `.fna` file under `jobs/<job-id>/inputs/`, disable annotation, BiG-SCAPE, summary, clinker, figures, NPLinker, external artifact capture, downloads, and image pulls. Expected result is ClusterWeave `success`, Slurm `COMPLETED`, and generated public result manifest/archive.

## Backend validation

Before enabling user submissions, run the focused backend, job-store, web-auth,
and syntax checks from the repository root:

```bash
python3 -B -m unittest tests.test_slurm_backend tests.test_job_store_atomic
python3 -B -m unittest tests.test_web_api_auth
python3 -B -m py_compile web/app.py web/worker.py web/job_store.py web/runtime_capabilities.py web/canonical_pipeline.py web/slurm_backend.py
```

Then complete the tiny scheduler and Apptainer checks above with the real
account, partition, QOS, shared storage, and compute-node policy. A prior
site-specific run is not evidence that a new deployment, filesystem, allocation,
or tool cache is ready.

## Container and SIF caches

Do not require Docker on CADES compute nodes. Use Apptainer or Singularity and keep SIF/cache paths on approved shared storage.

Recommended placeholders:

```bash
CLUSTERWEAVE_SOFTWARE_ROOT=<SHARED_CLUSTERWEAVE_SOFTWARE_CACHE_DIR>
APPTAINER_CACHEDIR=<SHARED_APPTAINER_CACHE_DIR>
SINGULARITY_CACHEDIR=<SHARED_SINGULARITY_CACHE_DIR>
```

When `singularity` is an Apptainer compatibility command, keep `SINGULARITY_CACHEDIR` equal to `APPTAINER_CACHEDIR` to avoid cache-selection warnings.

Suggested SIF placeholders:

```bash
ANTISMASH_SIF=<SHARED_CLUSTERWEAVE_SOFTWARE_CACHE_DIR>/antismash/antismash_standalone.sif
FUNBGCEX_SIF=<SHARED_CLUSTERWEAVE_SOFTWARE_CACHE_DIR>/funbgcex/funbgcex_bundle.sif
BIGSCAPE_SIF_PATH=<SHARED_CLUSTERWEAVE_SOFTWARE_CACHE_DIR>/bigscape/bigscape_2.0.0-beta.6.sif
CLINKER_SIF_PATH=<SHARED_CLUSTERWEAVE_SOFTWARE_CACHE_DIR>/clinker/clinker-py_0.0.32--pyhdfd78af_0.sif
```

Prebuild or pre-stage large SIF assets where policy allows. Avoid job-time downloads for public runs whenever possible.

### Stage antiSMASH SIF

ClusterWeave's annotation stage expects:

```bash
ANTISMASH_SIF=<SHARED_CLUSTERWEAVE_SOFTWARE_CACHE_DIR>/antismash/antismash_standalone.sif
ANTISMASH_IMAGE_URI=docker://antismash/standalone:8.0.4
```

Stage the antiSMASH SIF with a Slurm job so the pull/conversion happens on a compute node using the same scratch-backed cache policy as real jobs. Omit the `#SBATCH --qos` line if the chosen allocation does not use QOS.

```bash
STAGE_ROOT="<SHARED_CLUSTERWEAVE_ROOT>/sif_stage"
mkdir -p "$STAGE_ROOT" "$(dirname "$ANTISMASH_SIF")" "$APPTAINER_CACHEDIR"

cat > "$STAGE_ROOT/stage_antismash.sbatch" <<EOF
#!/usr/bin/env bash
#SBATCH --job-name=cw-stage-antismash
#SBATCH --account=$CLUSTERWEAVE_SLURM_ACCOUNT
#SBATCH --partition=$CLUSTERWEAVE_SLURM_PARTITION
#SBATCH --qos=$CLUSTERWEAVE_SLURM_QOS
#SBATCH --nodes=1
#SBATCH --cpus-per-task=2
#SBATCH --mem=8G
#SBATCH --time=01:00:00
#SBATCH --chdir=<SHARED_CLUSTERWEAVE_ROOT>
#SBATCH --output=$STAGE_ROOT/stage_antismash_%j.out
#SBATCH --error=$STAGE_ROOT/stage_antismash_%j.err

set -euo pipefail
export APPTAINER_CACHEDIR=$APPTAINER_CACHEDIR
export SINGULARITY_CACHEDIR=$APPTAINER_CACHEDIR
export ANTISMASH_SIF=$ANTISMASH_SIF
export ANTISMASH_IMAGE_URI=\${ANTISMASH_IMAGE_URI:-docker://antismash/standalone:8.0.4}

mkdir -p "\$(dirname "\$ANTISMASH_SIF")" "\$APPTAINER_CACHEDIR"
hostname -f
apptainer --version
echo "ANTISMASH_SIF=\$ANTISMASH_SIF"
echo "ANTISMASH_IMAGE_URI=\$ANTISMASH_IMAGE_URI"
apptainer pull --force "\$ANTISMASH_SIF" "\$ANTISMASH_IMAGE_URI"
apptainer exec "\$ANTISMASH_SIF" sh -lc 'command -v antismash; antismash --version'
ls -lh "\$ANTISMASH_SIF"
EOF

sbatch --parsable "$STAGE_ROOT/stage_antismash.sbatch"
```

After the staging job finishes:

```bash
sacct -j <SLURM_JOB_ID> --format=JobID,State,ExitCode,Elapsed,NodeList -P
cat "$STAGE_ROOT/stage_antismash_<SLURM_JOB_ID>.out"
cat "$STAGE_ROOT/stage_antismash_<SLURM_JOB_ID>.err"
ls -lh "$ANTISMASH_SIF"
```

Proceed only if Slurm reports `COMPLETED|0:0`, the SIF exists, and `antismash --version` runs inside the container. Then add the final `ANTISMASH_SIF` and `ANTISMASH_IMAGE_URI` values to the deployment env file and keep `AUTO_PULL_IMAGES=never` for production-like runs.

antiSMASH image conversion is substantially heavier than the Alpine preflight.
Allocate memory, scratch space, and walltime from measurements on the target
filesystem, inspect Slurm MaxRSS and exit status, and proceed only when the SIF
exists and `antismash --version` succeeds inside it.

Before attempting a real annotation run, choose and document the approved shared locations for:

- `DATA_DIR`: job metadata, uploads, logs, work directories, and public result archives.
- `CLUSTERWEAVE_SOFTWARE_ROOT`: SIFs, tool caches, reference data, and helper environments.
- `APPTAINER_CACHEDIR`: temporary OCI blobs and Apptainer cache material.

These locations must be visible from the login/service node and Slurm compute nodes, have enough quota for concurrent jobs, and be excluded from source control.

## Security notes

- Do not commit secrets, CADES usernames, allocation IDs, SSH keys, tokens, private hostnames, or host-specific paths.
- Do not mount the Docker socket in the public portal path.
- Do not run scientific workload on login nodes; the Slurm submitter should only claim queue files, write scripts, submit, poll, and cancel.
- Keep raw scheduler logs and internal paths admin-only.
- Do not place sensitive genomes or private user data on a public portal unless the deployment policy explicitly allows it.
- Keep result tokens and `CLUSTERWEAVE_JOB_TOKEN_SECRET` stable and private.
- Keep retention sweeping active for public deployments.
