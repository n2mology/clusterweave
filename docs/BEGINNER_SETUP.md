# Beginner setup

This tutorial starts with a clean computer and ends with one small accession job
in the ClusterWeave browser interface. ClusterWeave uses Docker, which runs the
web service, worker, scientific tools, and reference data in containers. Docker
Compose reads `docker-compose.yml` and starts the related containers together.
You do not need to install the scientific tools one at a time.

Web-hosted access is **coming soon**. Therefore, this tutorial uses the trusted
local Docker profile. The release has been validated on Linux x86_64, and the
sections below explain the corresponding Docker Desktop setup for WSL2, Intel
macOS, and Apple Silicon.

## Before you begin

Use a computer on which you are allowed to run Docker. Give Docker at least 4
CPUs and 16 GiB of memory. Disk use varies with the genomes and retained
results; the first bootstrap alone includes approximately 6 GiB of antiSMASH and
Pfam reference data in addition to image layers and temporary files, so a first
user should begin with tens of GiB free and check growth during real analyses.

The local profile mounts the host Docker socket. The socket lets the
ClusterWeave worker start pinned scientific-tool containers, but it also gives
the worker substantial control over Docker on the machine. Use this profile only
for a trusted local user, keep it bound to `127.0.0.1`, and do not expose it to a
public or untrusted network.

A few terms used below:

- A **repository** is the downloaded ClusterWeave source directory.
- An **accession** is an NCBI identifier for a particular genome assembly.
- A **worker** is the ClusterWeave process that takes one queued job and runs the
  canonical shell workflow.
- A **BGC** is a biosynthetic gene cluster predicted from neighboring genes.
- A **GCF** is a gene cluster family inferred from related BGC records.
- A **local instance** is the web service and worker running through Docker on
  your own computer.

## Choose the instructions for your computer

### Windows with WSL2

Windows users run one installation command in an administrator PowerShell, then
run the ClusterWeave commands in an Ubuntu/WSL terminal. Windows Subsystem for
Linux 2 (WSL2) supplies the Linux shell, while Docker Desktop supplies the
Docker daemon.

1. Follow Microsoft's [official WSL installation guide](https://learn.microsoft.com/en-us/windows/wsl/install).
   Open **PowerShell as Administrator** and run:

   ```powershell
   wsl --install
   ```

   Restart Windows if prompted. Open Ubuntu from the Start menu and create the
   requested Linux username and password.

2. Back in PowerShell, confirm that Ubuntu uses WSL version 2:

   ```powershell
   wsl --list --verbose
   ```

   The `VERSION` column should show `2` for the distribution you will use.

3. Install [Docker Desktop for Windows](https://docs.docker.com/desktop/setup/install/windows-install/).
   In Docker Desktop settings, enable the WSL2 engine and integration for the
   Ubuntu distribution. Start Docker Desktop before continuing.

4. Open the **Ubuntu/WSL terminal**. Keep the repository in the Linux filesystem
   (for example, under your Ubuntu home directory) rather than under `/mnt/c/`,
   because the Linux filesystem normally gives Docker and the workflow better
   file-I/O behavior. Install Git if Ubuntu does not already provide it:

   ```bash
   sudo apt update
   sudo apt install -y git curl
   ```

All remaining Bash commands in this tutorial go in the Ubuntu/WSL terminal, not
PowerShell.

### Linux

Linux users run all commands in the normal terminal for their distribution.
Install Git, Docker Engine, and the Docker Compose v2 plugin from the official
instructions for the distribution:

- [Docker Engine installation](https://docs.docker.com/engine/install/)
- [Docker Compose plugin installation](https://docs.docker.com/compose/install/linux/)
- [Git downloads and platform instructions](https://git-scm.com/downloads/)

Start the Docker daemon according to the distribution's service policy. On a
systemd distribution, the usual check is:

```bash
sudo systemctl status docker
```

The user who runs ClusterWeave must be allowed to use the Docker daemon. Docker's
Unix group is effectively privileged; follow Docker's official post-install
instructions and the local security policy rather than making the socket
world-writable.

### macOS

macOS users run all ClusterWeave commands in **Terminal** or another
Bash-compatible shell. Install:

- [Docker Desktop for Mac](https://docs.docker.com/desktop/setup/install/mac-install/)
- [Git](https://git-scm.com/downloads/)

Start Docker Desktop and wait until the Docker engine reports that it is
running. The ClusterWeave compatibility default is `linux/amd64`. Intel Macs run
that architecture directly; Apple Silicon uses Docker Desktop's amd64
emulation, which is expected to be slower. Do not change the platform merely to
remove a warning, because the scientific images must remain on a mutually
compatible architecture.

## Verify Docker, Compose, and resources

Run these commands in the Ubuntu/WSL, Linux, or macOS terminal selected above:

```bash
git --version
docker --version
docker compose version
docker info
docker run --rm hello-world
```

The commands should print versions, Docker daemon information, and a successful
`hello-world` message. `docker compose version` must use the two-word Compose v2
form. If `docker info` reports that it cannot connect, stop here and use the
[daemon troubleshooting section](#docker-daemon-is-unavailable-or-permission-is-denied).

Check the resources visible to Docker and the available disk:

```bash
docker info --format 'CPUs: {{.NCPU}}'
docker info --format 'Memory bytes: {{.MemTotal}}'
docker system df
df -h .
```

Docker should report at least 4 CPUs and approximately 17,179,869,184
memory bytes (16 GiB); a virtualized engine can report slightly less after
overhead, so confirm the configured allocation as well as the displayed value.
Docker Desktop users should also inspect **Settings > Resources**, because the
Docker virtual disk can have a separate limit from the host filesystem. If the
host has little free disk, make space before building or downloading reference
data; do not begin by deleting unknown Docker volumes.

## Download ClusterWeave

A Git clone and a tagged source archive contain the same release source, but
they are maintained differently:

- A **Git clone** retains Git metadata and can be inspected or updated with Git.
- A **tagged archive** is a fixed snapshot downloaded from the GitHub Releases
  page. An archive has no Git history and cannot be updated with `git pull`.

ClusterWeave v1.0.1 is the current public release. Use the
[ClusterWeave releases page](https://github.com/n2mology/clusterweave/releases)
when you need its immutable tag or source archive.

### Option A: clone with Git

Run these commands in your Ubuntu/WSL, Linux, or macOS terminal:

```bash
cd ~
git clone https://github.com/n2mology/clusterweave.git
cd clusterweave
```

For a reproducible v1.0.1 checkout, request the tag explicitly:

```bash
git clone --branch v1.0.1 --depth 1 https://github.com/n2mology/clusterweave.git
cd clusterweave
```

### Option B: use a tagged archive

Open the [ClusterWeave releases page](https://github.com/n2mology/clusterweave/releases)
in a browser, select the intended published version, download its source
archive, and extract it. Rename the extracted directory to `clusterweave` before
the first Docker start, then open a terminal in that directory. Keeping the
standard directory name also keeps the default Compose project and named-volume
names consistent with the local profile.

Whichever option you choose, confirm that the terminal is at the repository
root. The following command should list `README.md`, `docker-compose.yml`, and
`bin/`:

```bash
pwd
ls
```

## Initialize the private local configuration

From the repository root, run:

```bash
./bin/init_local_instance.sh
```

The initializer creates `.env` with mode `0600`, generates a job-token secret
and administrator token, binds the service to `127.0.0.1:8080`, and sets a
four-CPU, 16-GiB worker. It also sets
`CLUSTERWEAVE_MAX_CPUS_PER_JOB=4`, so the local web service does not accept a
public job larger than its default four-CPU worker can admit.

If `.env` already exists, the initializer leaves it unchanged. Do not paste the
contents of `.env` into an issue, email, screenshot, or support message. The
file contains credentials that protect local administrator actions and saved
result links.

## Build and start the local instance

Still at the repository root, run one command at a time:

```bash
docker compose build
docker compose up -d
docker compose ps
curl --fail http://127.0.0.1:8080/
```

`docker compose build` builds the ClusterWeave web and worker images.
`docker compose up -d` starts the containers in the background. `docker compose
ps` should show the `web` and `worker` services running, and the `curl` command
should return the HTML landing page without an HTTP error.

Open [http://127.0.0.1:8080](http://127.0.0.1:8080) in a browser on the same
computer. WSL2 users normally open this loopback address in their Windows
browser while Docker Desktop and the Ubuntu distribution remain running.

### Understand the first bootstrap

The web page may load before the scientific worker is ready. On the first
start, the worker prepares cached assets in this order:

1. antiSMASH reference databases (approximately 5 GiB),
2. the Pfam HMM database (approximately 1 GiB before indexes and working room),
3. the NCBI Datasets and Dataformat command-line tools,
4. pinned clinker and BiG-SCAPE container images,
5. the local FunBGCeX image, followed by the worker loop.

Follow the worker output:

```bash
docker compose logs -f worker
```

Expected milestones include `antiSMASH databases ready`, `Pfam-A.hmm ready`,
`NCBI datasets CLI ready`, image pull/build messages, and finally `Starting
ClusterWeave worker`. Some phases can take a long time on a first run. Press
`Ctrl-C` when you want to stop following the text; the containers continue to
run in the background.

A warning that an optional pull will retry later is different from a ready core
runtime. Before submitting an accession, confirm that the browser no longer
reports the required accession/runtime capability as unavailable. The detailed
runtime and log interpretation are in [INSTALL.md](INSTALL.md).

## Submit one small accession run

This first run checks the installed interface and the bacterial taxonomy route.
It is not a biological benchmark, and a small genome can legitimately produce
few or no BGC calls.

1. Open **INPUT STATION** and keep **New run** selected.
2. Choose **Bacteria** as the analysis scope.
3. Enter the public example accession `GCF_000005845.2` in the NCBI accession
   list. This is *Escherichia coli* K-12 substrain MG1655 from the mixed example.
4. Enter `first_bacteria` as the project name. Leave target genome and ecology
   unset for this first run.
5. Select **Submit run** and wait for input verification to finish.
6. In **Save your result access**, copy the private result link to a secure local
   note. You may instead save the job ID and result access code as a pair.
7. Select **Open run progress**.

The **BGC WORKFLOW STATION** shows the active stage and per-genome milestones.
The worker may need considerable time even for one accession because annotation
and database comparisons are real scientific computations. A queued state is
normal while the single default worker is busy.

When the run reaches a terminal state, **RESULT BLOCKS** shows the applicable
output tabs. **FUNBGCEX** is absent or not applicable for this bacterial run;
that is expected. Use **ANTISMASH**, **BIG-SCAPE**, **CLINKER**, **SUMMARY**, and
**FIGURES** only when the corresponding output exists. Select **Download
package** when you want to keep the run for review outside the browser.
ClusterWeave downloads one ZIP workbench archive containing the derived reports
and tables, the staged genome GenBank files, the antiSMASH region GenBank files,
and the canonical FunBGCeX BGC GenBank files when FunBGCeX applies.

The archive also contains a redacted evidence manifest with the size and
SHA-256 checksum of every included genome or BGC GenBank file. These package-only
files are not exposed as a separate result tab. Because the package contains
genome and BGC sequences, keep the result link private whenever the submitted
genomes are not public.

## Reopen results later

A result link contains a bearer credential. Anyone with the link can read the
allowlisted result until it expires or is removed, so store the link privately.

To reopen a run:

1. Open the local ClusterWeave page.
2. In **INPUT STATION**, select **Existing results**.
3. Paste the full private result link and select **Load result**.
4. If you saved separate values, paste the job ID under **Result link or job
   ID**, paste the result access code under **Access code**, apply the code, and
   load the result.

The **RUN STACK** remembers runs only for the current browser context. Saving the
private result link outside the browser is therefore the reliable return path.

## Stop and restart

Stop the containers while preserving their named volumes:

```bash
docker compose stop
```

Restart the same local instance:

```bash
docker compose start
docker compose ps
curl --fail http://127.0.0.1:8080/
```

`docker compose up -d` is also safe when services need to be recreated after a
configuration or image change. Never run `docker compose down -v` for routine
maintenance: `-v` deletes the job and database volumes.

## Back up job data

The following backup stops writes, archives the job-data volume, and then starts
the services again. Run it from the repository root:

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

The archive contains uploads, private job metadata, logs, and results, so protect
it as sensitive data. The antiSMASH and Pfam named volumes are caches and can be
prepared again; an operator who must preserve those caches should back them up
separately using the same read-only-volume method.

## Update safely

Read [CHANGELOG.md](../CHANGELOG.md) and make a backup before changing versions.
Do not update while a job is running.

For a checkout following its current branch:

```bash
git status --short
git pull --ff-only
docker compose build
docker compose up -d
curl --fail http://127.0.0.1:8080/
```

Stop if `git status --short` reports edits you do not understand; do not discard
them merely to make an update proceed.

For a version-pinned Git checkout, fetch tags and switch only to a tag that is
actually published and reviewed:

```bash
git fetch --tags origin
git tag --list
git switch --detach v1.0.1
docker compose build
docker compose up -d
```

A source archive cannot use Git commands. Download the next published archive
into a separate directory, preserve the old directory and backup, review the
new release notes, and copy the private `.env` only on the same trusted machine.
Keep the active directory named `clusterweave` so Compose reuses the intended
named volumes. The technical update notes are in
[INSTALL.md](INSTALL.md).

## Troubleshooting

### Docker daemon is unavailable or permission is denied

If `docker info` says it cannot connect, make sure Docker Desktop is running on
Windows or macOS. On Linux, inspect the service:

```bash
sudo systemctl status docker
sudo systemctl start docker
```

If `sudo docker info` works but `docker info` does not, the current Linux user
lacks daemon access. Follow Docker's official post-install instructions and the
local administrator's policy, then start a new login session. Do not use
`chmod 666` on the Docker socket; that would grant every local user privileged
Docker access.

On WSL2, confirm that Docker Desktop integration is enabled for the same Ubuntu
distribution in which you cloned ClusterWeave. Run `wsl --list --verbose` in
PowerShell and `docker info` in Ubuntu.

### Port 8080 is already in use

One possible explanation for a web container that will not start is another
program already listening on port 8080. Edit the private `.env` and change both
values together, for example:

```text
HOST_PORT=8081
CLUSTERWEAVE_PUBLIC_BASE_URL=http://127.0.0.1:8081/
```

Then recreate the services and open the new loopback URL:

```bash
docker compose up -d
curl --fail http://127.0.0.1:8081/
```

Keep `CLUSTERWEAVE_BIND_ADDRESS=127.0.0.1`.

### The worker runs out of memory

An exit status of 137, an `OOMKilled` container state, or an abrupt tool exit can
mean Docker did not have enough memory. Check:

```bash
docker compose ps
docker inspect clusterweave-worker --format '{{.State.OOMKilled}}'
docker compose logs --tail=200 worker
```

Give Docker at least 16 GiB, close other memory-heavy work, and retry one small
job. Do not increase genome parallelism, per-stage CPUs, or worker concurrency
while investigating a memory failure. Large fungal annotations may require more
than the portable minimum.

### Apple Silicon reports an architecture or emulation problem

The generated `.env` should contain:

```text
CLUSTERWEAVE_DOCKER_PLATFORM=linux/amd64
```

Confirm that Docker Desktop is able to run amd64 images, then rebuild. Emulation
is slower. An `exec format error` usually means the selected platform and an
image architecture disagree; retain the documented amd64 setting while
collecting the exact failing image and log.

### Downloads or bootstrap do not finish

Check network access, proxy rules, Docker registry access, and free disk before
retrying. The first bootstrap needs NCBI, EBI/Pfam, upstream container
registries, and several GiB of persistent storage. Review the last messages:

```bash
docker compose logs --tail=300 worker
docker system df
df -h .
```

After correcting a transient network or disk problem, restart only the worker so
completed cached assets remain available and missing phases retry:

```bash
docker compose restart worker
docker compose logs -f worker
```

Do not delete named volumes as a first troubleshooting step. If a reference
volume appears incomplete, retain the logs and use the detailed recovery advice
in [INSTALL.md](INSTALL.md) before removing any data.

### The web page opens but no job progresses

The web service and worker are separate containers. Inspect both:

```bash
docker compose ps
docker compose logs --tail=200 web worker
```

A bootstrapping worker is not yet ready to claim jobs. Similarly, a job can stay
queued while another job holds the four-CPU worker budget. If the worker reports
that a job cannot fit, confirm that `.env` keeps
`CLUSTERWEAVE_MAX_CPUS_PER_JOB` at or below
`CLUSTERWEAVE_WORKER_CPU_LIMIT`; the initialized values are both 4.

### Collect useful logs without exposing secrets

For a local diagnosis, save the service state and the last bounded log section:

```bash
docker compose ps
docker compose logs --tail=200 web worker
```

Before sharing output, remove result links, access codes, job IDs, email
addresses, genome names that are not public, local paths, and any environment
values. Never share `.env`. Raw logs and complete job directories are private
operator material, even when the final public result package is safe.

For more detail, continue with [INSTALL.md](INSTALL.md). The scientific and
access boundaries are summarized in [README.md](../README.md) and
[WEB_RUNTIME.md](WEB_RUNTIME.md).
