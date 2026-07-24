# Installation and local operation

[BEGINNER_SETUP.md](BEGINNER_SETUP.md) is the patient, platform-specific
walkthrough. This document is the technical reference for the shipped Docker
profiles, generated configuration, first-start preparation, routine operations,
and recovery checks.

Web-hosted access is **coming soon**. The commands below start a private local
instance; they do not publish a service.

## Choose the correct Compose profile

`docker-compose.yml` is the complete trusted local profile. It builds a small
web/API container and a bounded worker container, stores data in named volumes,
and mounts the host Docker socket into the worker so the worker can launch
pinned scientific-tool containers. Keep the default loopback binding and use
this profile only on a trusted machine.

`clusterweave.yml` is deliberately socket-free. It requires a configured
external executor, such as the shipped Slurm backend, and is not a complete
laptop workflow. Operators should read [WEB_RUNTIME.md](WEB_RUNTIME.md) and
[CADES_SLURM_BACKEND.md](CADES_SLURM_BACKEND.md) before using that profile.

Version 1.0.1 targets Linux x86_64. WSL2 and macOS use the same pinned amd64
images through Docker Desktop, although host integration and Apple Silicon
emulation can affect performance.

## Prerequisites

Install from the official sources for the host:

- [Docker Engine](https://docs.docker.com/engine/install/) and the
  [Compose v2 plugin](https://docs.docker.com/compose/install/linux/) on Linux;
- [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/)
  with WSL2 integration on Windows;
- [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/)
  on Intel or Apple Silicon macOS;
- [Git](https://git-scm.com/downloads/) on every platform.

Verify the client, Compose plugin, daemon, and available resources from the
terminal that will run ClusterWeave:

```bash
git --version
docker --version
docker compose version
docker info
docker info --format 'CPUs: {{.NCPU}}'
docker info --format 'Memory bytes: {{.MemTotal}}'
docker system df
df -h .
```

The portable local target is at least 4 Docker CPUs and 16 GiB of Docker memory.
Disk must cover image layers, approximately 6 GiB of initial antiSMASH/Pfam data,
per-job work, and retained results. Large fungal assemblies and repeated jobs
can require substantially more than the minimum.

## Source checkout

Clone the current repository:

```bash
git clone https://github.com/n2mology/clusterweave.git
cd clusterweave
```

For an archival analysis, select the version from the
[releases page](https://github.com/n2mology/clusterweave/releases) or clone the
v1.0.1 tag directly:

```bash
git clone --branch v1.0.1 --depth 1 https://github.com/n2mology/clusterweave.git
cd clusterweave
```

A GitHub source archive has no Git history and cannot be updated with
`git pull`. Extracted archive users should rename the working directory to
`clusterweave` before the first Compose start so the local profile uses its
expected default project and named-volume names.

## Initialize the local profile

Run the initializer once from the repository root:

```bash
./bin/init_local_instance.sh
```

The initializer is idempotent. When `.env` does not exist, it creates the file
with mode `0600`, generates a stable job-token secret and administrator token,
and writes these local defaults:

| Setting | Initial value | Purpose |
| --- | --- | --- |
| `CLUSTERWEAVE_BIND_ADDRESS` | `127.0.0.1` | Host interface exposed by Compose |
| `HOST_PORT` | `8080` | Host HTTP port |
| `CLUSTERWEAVE_DOCKER_PLATFORM` | `linux/amd64` | Common architecture for worker and sibling tools |
| `CLUSTERWEAVE_PUBLIC_BASE_URL` | `http://127.0.0.1:8080/` | Base used for local result links |
| `CLUSTERWEAVE_WORKER_CPU_LIMIT` | `4` | Worker-container CPU ceiling |
| `CLUSTERWEAVE_MAX_CPUS_PER_JOB` | `4` | Maximum public job accepted by the web service |
| `CLUSTERWEAVE_WORKER_MEM_LIMIT` | `16g` | Worker-container memory ceiling |
| `PIPELINE_CPUS` | `4` | Default scientific job budget |

The accepted per-job limit must remain at or below the worker limit. Raising
`CLUSTERWEAVE_WORKER_CPU_LIMIT` alone does not authorize larger public jobs;
operators who deliberately raise `CLUSTERWEAVE_MAX_CPUS_PER_JOB` must first
measure the host and keep worker admission, memory, process, and disk budgets
coherent.

When `.env` already exists, the initializer prints that it kept the file and
makes no changes. Preserve `CLUSTERWEAVE_JOB_TOKEN_SECRET` across restarts and
upgrades because saved result links and completion indexes depend on it. Never
commit or share `.env`.

Inspect the resolved Compose model before a first start or configuration change:

```bash
docker compose config --quiet
docker compose config --services
docker compose config --volumes
```

## Build and start

```bash
docker compose build
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8080/
```

The web service can answer before the worker completes first-start preparation.
The worker stores preparation state under the job-data volume and downloads or
prepares:

- antiSMASH databases under the antiSMASH named volume;
- Pfam-A plus its indexes under the Pfam named volume;
- NCBI Datasets and Dataformat under the shared software directory;
- pinned BiG-SCAPE and clinker images;
- the repository-built FunBGCeX image.

Follow worker preparation:

```bash
docker compose logs -f worker
```

A normal first-start sequence reports the antiSMASH, Pfam, NCBI CLI, clinker,
BiG-SCAPE, and FunBGCeX phases before `Starting ClusterWeave worker`. The exact
download time depends on network and disk performance. Cached assets are reused
on later starts.

Inspect both services without following indefinitely:

```bash
docker compose ps
docker compose logs --tail=200 web worker
curl --fail http://127.0.0.1:8080/api/system/status
```

The anonymous status response is intentionally redacted in public mode. The UI
uses the same endpoint to disable required stages that are not ready.

## Platform notes

### Linux

Use a supported Docker Engine and Compose plugin. The account running
ClusterWeave must have daemon access under local policy. Membership in Docker's
Unix group is privileged; do not make `/var/run/docker.sock` world-writable.

### Windows and WSL2

Use Docker Desktop's WSL2 backend and enable integration for the Linux
distribution that holds the repository. Keep the checkout in the WSL Linux
filesystem rather than under `/mnt/c/` for more predictable file I/O. Run
Compose from the WSL shell, while the browser may run on Windows and open the
same loopback URL.

### Intel macOS

Docker Desktop runs the default `linux/amd64` containers without cross-CPU
emulation. Confirm that Docker Desktop receives at least 4 CPUs and 16 GiB in
its resource settings.

### Apple Silicon macOS

The compatibility default remains `CLUSTERWEAVE_DOCKER_PLATFORM=linux/amd64`,
so Docker Desktop uses amd64 emulation for the worker and sibling images. This
is slower than native execution; allow extra bootstrap and job time.

## Routine operations

```bash
# Read recent logs.
docker compose logs --tail=200 web worker

# Follow the worker; Ctrl-C stops following, not the container.
docker compose logs -f worker

# Stop without deleting data.
docker compose stop

# Restart the stopped containers.
docker compose start

# Reconcile containers after a build or .env change.
docker compose up -d
```

Never use `docker compose down -v` for routine operation or an upgrade. The
`-v` option deletes named volumes containing job data and downloaded databases.

## Back up the job-data volume

Stop the services so the archive has a consistent view, then create a timestamped
archive from the read-only volume:

```bash
mkdir -p backups
backup_file="clusterweave-job-data-$(date +%Y%m%d-%H%M%S).tar.gz"
docker compose stop
docker run --rm \
  -v clusterweave_job_data:/source:ro \
  -v "$PWD/backups":/backup \
  alpine:3.22 \
  tar -czf "/backup/$backup_file" -C /source .
ls -lh "backups/$backup_file"
docker compose start
```

The backup contains uploads, private metadata, logs, work products, results, and
read-token digests. Store it as private data. The antiSMASH and Pfam volumes are
rebuildable caches; sites that need offline recovery should archive those named
volumes separately and record the tool/data versions.

A restore overwrites active state and therefore requires an explicit recovery
plan. Stop the services, preserve the current volume, validate the archive, and
restore into a newly created volume rather than extracting over a running
instance.

## Upgrade without deleting volumes

Do not upgrade while a job is queued or running. Read the changelog, back up the
job-data volume, and confirm that the worktree has no unexplained edits:

```bash
git status --short
git pull --ff-only
docker compose build
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8080/
```

For a pinned deployment, fetch and inspect published tags, then switch only to
the version approved by the operator:

```bash
git fetch --tags origin
git tag --list
git switch --detach v1.0.1
docker compose build
docker compose up -d
```

An archive checkout is replaced with a separately downloaded, reviewed archive;
it is not updated in place. Preserve the old source directory and backup until
the new services and saved result access have been checked. Transfer `.env`
only between trusted local directories, retain the directory name
`clusterweave`, and never copy the secret file into a public archive.

## External executor profile

`clusterweave.yml` runs with the Docker socket disabled and reports unavailable
required stages unless a real executor is configured. The shipped external path
uses `CLUSTERWEAVE_EXECUTOR=slurm`, a filesystem queue, scheduler submission,
and the canonical one-shot worker on the compute node. See
[CADES_SLURM_BACKEND.md](CADES_SLURM_BACKEND.md) for its environment and
preflight contract. Apptainer/Singularity instructions in that document are for
HPC operators, not prerequisites for the local Docker tutorial.

## Troubleshooting

### Docker daemon access

If `docker info` cannot connect, start Docker Desktop on Windows/macOS or inspect
the Linux service:

```bash
sudo systemctl status docker
sudo systemctl start docker
```

If only `sudo docker info` succeeds, correct the user/daemon relationship with
Docker's official post-install guidance and local policy. Do not run Compose
partly with `sudo` and partly without it, and do not use `chmod 666` on the
socket. In WSL2, confirm that Docker Desktop integration is enabled for the same
distribution where `docker info` is running.

### Port conflict

If Docker reports that `127.0.0.1:8080` is already allocated, change `HOST_PORT`
and `CLUSTERWEAVE_PUBLIC_BASE_URL` together in private `.env`, for example:

```text
HOST_PORT=8081
CLUSTERWEAVE_PUBLIC_BASE_URL=http://127.0.0.1:8081/
```

Then run `docker compose up -d` and open the new loopback URL. Keep
`CLUSTERWEAVE_BIND_ADDRESS=127.0.0.1` unless a separately reviewed network,
authentication, TLS, firewall, and executor design exists.

### CPU or memory admission failure

The initialized profile has a four-CPU worker and accepts at most four CPUs per
public job. Check the effective configuration:

```bash
docker compose config | grep -E 'cpus:|mem_limit|CLUSTERWEAVE_MAX_CPUS_PER_JOB|WORKER_CPU_BUDGET'
docker inspect clusterweave-worker --format 'CPUs={{.HostConfig.NanoCpus}} Memory={{.HostConfig.Memory}} OOM={{.State.OOMKilled}}'
```

Keep `CLUSTERWEAVE_MAX_CPUS_PER_JOB <= CLUSTERWEAVE_WORKER_CPU_LIMIT`. A job can
remain queued while active reservations use the worker budget. An exit status
of 137 or `OOM=true` suggests a memory kill; allocate more Docker memory or use a
smaller job, and do not increase concurrency or stage fan-out while diagnosing
it.

### Apple Silicon amd64 emulation

Confirm that `.env` retains:

```text
CLUSTERWEAVE_DOCKER_PLATFORM=linux/amd64
```

An `exec format error` or `no matching manifest` message usually identifies an
image/platform disagreement. Make sure Docker Desktop can emulate amd64 and
capture the exact image and log before changing the common platform. The
compatibility setting is deliberate because all sibling tools must agree on an
architecture.

### Download, registry, or bootstrap failure

Inspect worker logs and capacity:

```bash
docker compose logs --tail=300 worker
docker system df
df -h .
```

The first preparation needs outbound access to upstream registries and the NCBI
and Pfam sources. Corporate proxies, registry authentication limits, DNS
failure, full Docker storage, or an interrupted download can explain a stalled
phase. After correcting the cause, restart the worker; completed assets remain
cached and missing preparation retries:

```bash
docker compose restart worker
docker compose logs -f worker
```

Do not remove a named database volume as the first response. Preserve the logs
and identify the failed phase. If an operator eventually decides a cache is
unrecoverable, back up and resolve the exact volume before any removal.

### Web is reachable but the worker is not ready

```bash
docker compose ps
docker compose logs --tail=200 web worker
curl --fail http://127.0.0.1:8080/api/system/status
```

The web container can be healthy during worker bootstrap. The UI and API reject
a job that requires an unavailable stage. Wait for the required phase to become
ready, or use the worker log to resolve the failed preparation step.

### Accession download fails

Confirm that the NCBI CLI phase completed, that the accession is a current
assembly accession, and that outbound NCBI access works from the worker. An
accession-specific withdrawal or replacement is different from a general
network failure. Keep the original accession and error in private run evidence;
do not silently substitute a different assembly in a versioned example.

### Logs and support evidence

Collect bounded output:

```bash
docker compose ps
docker compose logs --tail=200 web worker
```

Remove private result links, access codes, job IDs, email addresses, sensitive
genome names, and local paths before sharing. Never share `.env`, a complete job
directory, or raw logs from a public-facing service. Public packages are
allowlisted precisely because ordinary runtime state is private.
