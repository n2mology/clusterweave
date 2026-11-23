# Confined Linux SIF deployment

This profile runs prepared scientific tools inside a nonroot worker. Docker is
used by the operator to build and start the services. Neither service receives
a Docker socket, Docker group membership, or a privileged dispatcher.
SIF commands use non-setuid Apptainer with separate user, mount, PID and network
namespaces. This profile requires Linux amd64, AppArmor, user namespaces, FUSE,
and Docker Compose with `!override` support. Windows/WSL2 and Docker Desktop
execution of this profile are unmeasured.

## Prepare images and assets

Build the complete `Dockerfile.web` and `Dockerfile.worker` recipes from the same
source export. Record the resulting image IDs with `docker image inspect` and
use those exact `sha256:` identities in configuration. The web build includes a
corresponding-source download for modified plantiSMASH at
`/assets/third-party/plantismash-source.zip`.

Run [plant source preparation](PLANTISMASH_RUNTIME.md) explicitly. Prepare the
other selected tool SIFs and NCBI clients before starting the worker. Existing
local tool images can be packaged without giving the builder daemon access:

```bash
python3 software/plantismash/package_sif.py \
  --image YOUR_PINNED_LOCAL_TOOL_IMAGE \
  --worker-image YOUR_COMPLETE_WORKER_IMAGE \
  --output /path/to/new-software/TOOL/TOOL.sif \
  --preserve-image-timestamps
```

Preserve timestamps for these existing tool images. In particular, antiSMASH
checks that prepared HMM files are newer than their source metadata; flattening
those times can trigger a forbidden write inside its read-only SIF. This option
is separate from the fixed-epoch reproducible plant source recipe. Verify
antiSMASH prerequisites and an actual detector run after packaging.

Large images need room for the exported archive, unpacked filesystem and SIF.
On a machine with sufficient available RAM, `--tmpfs-build-gib 24` moves the
unpacked filesystem into a 24 GiB memory filesystem and sets a 32 GiB builder
memory limit. It retains the two-CPU, 256-PID and 1,800-second limits. Use
`--max-export-bytes` and `--min-free-bytes` to enforce a prospective export bound
and disk reserve. The default unpacking uses disk and an 8 GiB builder limit.
Failed attempts remain available for diagnosis; never prune unrelated data to
make a build fit. A retained export can be reused on the same filesystem with
`--reuse-export /path/to/image.tar --reuse-export-sha256 SHA256_FROM_RECEIPT`.
The packager checks its checksum and embedded image identity before creating a
hard link; it preserves the original export after success or failure.

BiG-SCAPE writes SQLite temporary files under its job-specific
`big_scape/.tmp` directory. Include that directory in job disk monitoring;
large comparisons must not rely on Apptainer’s small session `/tmp`.
antiSMASH uses a private per-invocation directory under `WORK_ROOT/tmp` for
its working directory and `TMPDIR`, `TMP`, and `TEMP`. This keeps Prodigal
training files and DIAMOND search scratch on the bound job filesystem. Include
peak tool scratch in the job disk budget. A required detector failure stops
the workflow before grouping; partial outputs and the run manifest remain
available for diagnosis and are not a successful zero-call result.

Record the input image digest, output SIF checksum and build receipt. Use the
runtime paths below; a path is not proof that its contents are usable:

| Component | Path inside the worker |
| --- | --- |
| plantiSMASH | `/data/software/plantismash/plant.sif` |
| antiSMASH | `/data/software/antismash/antismash_standalone.sif` |
| FunBGCeX | `/data/software/funbgcex/funbgcex_bundle.sif` |
| Funannotate | `/data/software/funannotate/funannotate_v1.8.17.sif` |
| BiG-SCAPE | `/data/software/big_scape/bigscape_2.0.0-beta.6.sif` |
| clinker | `/data/software/clinker/clinker-py_0.0.32--pyhdfd78af_0.sif` |
| NPLinker Python | `/data/software/nplinker/nplinker_python3.11.sif` |
| Optional sequence phylogeny | `/data/software/phylogeny/clusterweave_phylogeny_1.0.0.sif` |
| NCBI clients | `/data/software/ncbi_cli/datasets` and `dataformat` |

NPLinker also needs its explicitly prepared Python environment; its SIF alone
is insufficient. Before starting services, create the environment using the same
exact Python image that produced its SIF. With the new software volume already
owned by UID/GID 65534, the operator can run:

```bash
docker run --rm --user 65534:65534 --read-only --cap-drop ALL \
  --security-opt no-new-privileges --cpus 2 --memory 4g --pids-limit 256 \
  --tmpfs /tmp:rw,exec,nosuid,nodev,size=1g -e HOME=/tmp \
  --mount type=volume,source=INSTANCE_software,target=/data/software,volume-nocopy \
  --entrypoint sh YOUR_EXACT_NPLINKER_PYTHON_IMAGE -c '
    set -eu
    test ! -e /data/software/nplinker/venv
    python -m venv --copies /data/software/nplinker/venv
    /data/software/nplinker/venv/bin/python -m pip install \
      --disable-pip-version-check --no-cache-dir \
      --report /data/software/nplinker/install-report.json nplinker==2.0.0
    /data/software/nplinker/venv/bin/python -m pip freeze --all \
      > /data/software/nplinker/requirements.freeze.txt
    printf "2.0.0\n" > /data/software/nplinker/venv/.clusterweave-nplinker-version
  '
```

Replace the two uppercase placeholders with the instance volume and recorded
image ID. Preparation requires HTTPS access to the Python package index and its
download hosts. Retain the install report and resolved dependency versions.
`--copies` keeps the interpreter executable visible to readiness checks outside
the SIF; execution still uses the matching Python libraries inside the SIF.
If preparation fails, preserve that environment and prepare a new software
root instead of silently merging or replacing its contents.

Package the existing `clusterweave-phylogeny:1.0.0` image by its recorded image ID
when sequence phylogeny is selected. The confined profile discovers its SIF at
the path above. Optional annotation/phylogeny stages retain their existing model
and reference requirements. No normal job may install missing software.
Retain the exact Pfam and MIBiG identities used for comparisons. Mount reference
volumes read-only and place the prepared MIBiG cache under
`/data/software/big_scape/resources/mibig_cache`.

## Create an isolated instance

The default worker configuration uses one job at a time, four CPUs,
16 GiB RAM and 1,024 processes. Explicit resource limits are configurable as
described under [Resource configuration](#resource-configuration). Review throughput and per-job memory before
moving an existing deployment to it. Keep the web admission floor and worker
free-space floor consistent with the measured storage required for outputs and
rollback; the default is not evidence that an arbitrary cohort will fit.

Use a private environment file with mode 0600. Set `CLUSTERWEAVE_INSTANCE` to a
unique lowercase name; `CLUSTERWEAVE_WEB_IMAGE` and
`CLUSTERWEAVE_WORKER_IMAGE` to the exact image IDs; and
`CLUSTERWEAVE_ANTISMASH_VOLUME` and `CLUSTERWEAVE_PFAM_VOLUME` to the selected
prepared reference volumes. Set `HOST_PORT` to an unused loopback port. Supply
new submit/admin credentials and a job-token secret using the existing
[access configuration](WEB_RUNTIME.md). Do not reuse another instance's
credentials or writable volumes.

Render and inspect the complete model, including the worker template:

```bash
docker compose --env-file /path/to/instance.env -f docker-compose.sif.yml \
  --profile sif-worker-template config --format json > /path/to/instance.json
chmod 600 /path/to/instance.json
```

The model names separate `${CLUSTERWEAVE_INSTANCE}_job_data`, `_software`,
`_accession_cache` and `_default` network resources. Prepare those named volumes
explicitly. New job-data and accession-cache volume roots must belong to
UID/GID 65534, which both services use. Copy the verified software tree into
the instance software volume before mounting it read-only. Do not initialize
or change ownership of another instance's volumes. Preserve credentials,
configuration and preparation receipts outside the public checkout.

Load the scoped AppArmor policy as described in
[the security profile instructions](../config/security/README.md). Start web
using the same environment file and Compose file with `up -d --no-build web`.
The worker template is excluded from normal Compose startup. Render its
one-shot creation specification and inspect it before creation:

```bash
python3 bin/sif_worker_container.py /path/to/instance.json \
  --output /path/to/worker-specification.json
```

The adapter rejects socket/bind mounts, foreign writable volumes, privileged
settings, unconfined profiles, remote Docker endpoints, mutable image tags and
resource expansion. It supplies the measured per-path proc policy that Compose
cannot express. Creation requires operator access to the local daemon; use a
new output filename when adding `--create`. It creates only the named worker
and never updates or removes a container. Start that worker explicitly with
`docker start INSTANCE-worker` after checking its mounted asset identities.
The adapter initially sets no automatic restart. If the service is intended to
survive daemon or host restarts, set its reviewed policy explicitly after
validation, for example `docker update --restart unless-stopped INSTANCE-worker`.
Preserve the prior restart policy when replacing an existing live deployment,
and verify readiness after a restart before reopening intake.

Check its logs, preparation status and authenticated service readiness before
submitting work. `check-runtime` must execute the prepared plant SIF under the
actual worker confinement; an image build or existing file alone is not a
readiness result. Scientific tools receive no external network; accession retrieval
runs in the application environment with NCBI HTTPS access.

## Stop, replace and roll back

The worker is managed explicitly, while web is managed by Compose. Stop only
the named worker and web services; do not run a broad prune. Keep job/software/
cache volumes and retained evidence. Before replacing a live instance, preserve
its exact images, configuration, security profiles and volume identities, and
capture a recoverable data point for any persistent schema or ownership change.
For existing data, inventory ownership, modes and mutable application state,
including `downloads/.clusterweave_result_index.v1.json`. Avoid a blanket
recursive ownership change: signed ZIP records include file identity metadata.
Leave already-readable immutable files and public ZIPs unchanged; transition
only directories, mutable state and private files that the service UID must
read. Verify archive identities and content hashes after the transition. A
rollback should change only differing ownership/modes, preserve new jobs outside
the restored queue and retain pre-restore state for diagnosis. File ctime cannot
be restored, so account explicitly for any identity-sensitive metadata changes.

Wait for queued/running jobs to finish. Never run old and new workers against
the same queue concurrently or substitute an empty candidate job volume.

Switch only the intended service endpoint. Verify authentication, existing
results, logs, downloads, readiness and a bounded fresh workflow. If the new
service fails those checks, stop its intake, retain diagnostics, and restore
the recorded services and any required data/permission recovery point. Confirm
health and historical access after restoration. Keep rollback images until the
observation and retention policy permits their removal.

## Resource configuration

The confined worker preserves explicit positive CPU, memory and PID limits from
the rendered configuration. The earlier 4-CPU/16-GiB smoke envelope is not a
profile maximum. `WORKER_CONCURRENCY` selects the maximum active jobs; aggregate
worker admission still reserves CPU and memory across every active job. Hosted
planning divides the advertised worker budget across that concurrency and caps
it by `CLUSTERWEAVE_MAX_CPUS_PER_JOB`. Genome and detector-record fan-out use
`CLUSTERWEAVE_PUBLIC_GENOME_PARALLELISM` and
`CLUSTERWEAVE_PUBLIC_ANTISMASH_RECORD_PARALLELISM`, bounded by that per-job share.
The CLI exposes `--concurrent-jobs`, `--genome-parallelism` and
`--record-parallelism` alongside its measured worker/job CPU and RAM settings.
Keep all confinement settings while changing capacity; do not infer capacity
from the old smoke values or bypass aggregate admission.
