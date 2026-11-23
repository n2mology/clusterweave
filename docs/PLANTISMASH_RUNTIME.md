# Supplied-CDS plant runtime

Plant submissions require translated GenBank CDS annotations and the pinned
plantiSMASH SIF. Matching FASTA can accompany the annotation. Missing or
incompatible annotations require a matching annotated input; the plant route
does not run a fungal annotation tool. See [plant inputs](PLANT_INPUTS.md).

## Default analysis features

The default run profile is `annotated-plants-2.0.4-extras-v3`. It enables
`--clusterblast`, `--subclusterblast`, `--knownclusterblast`, `--tfbs`, `--smcogs`,
`--full-hmmer`, and `--asf`, in addition to CD-HIT. Subgroup predictions and their
SVG trees are enabled by removing `--disable_subgroup`. Existing supplied-CDS,
plant models, core detection thresholds and bounded record/CPU scheduling remain
unchanged. The exact profile bytes are checksum-bound; modified defaults require
a distinct accepted run profile.

These are the implemented genome-only analysis extras. Coexpression requires an
expression dataset and is not possible from a genome alone. `--update_clusterblast`
is reference-database maintenance, not an analysis default. The pinned runner's
legacy `--inclusive` calls an undefined ClusterFinder implementation;
`--borderpredict` is parsed but unused. EC prediction calls an undefined module,
and the advertised `eco`/`sco` modeling choices are bacterial templates with no
implemented plant modeling execution. Enabling these switches would not supply
the corresponding scientific functionality. They are explicitly accounted for
in the profile rather than silently treated as supported.

The pinned preparation recipe supplies the complete implemented extras profile:
ClusterBlast, KnownClusterBlast and SubClusterBlast references, Pfam 27 and its
indexes, smCOG models/alignments and TreeGraph, subgroup reference packages and
GraPhlAn, ASF models/indexes, TFBS/ConnecTF/TAIR data, and the headless Java/font
runtime. Archive and extracted-file identities are fixed in the resource lock.
The offline build verifies tool prerequisites, exercises every ASF search/parser
configuration with a pinned reference protein, and renders a TreeGraph PNG.
These preparation probes are runtime checks, not findings for an analyzed genome.
Jobs do not acquire resources or generate missing indexes.

Prepare into a separate software root. Install the accepted SIF under a versioned
filename and set `PLANTISMASH_SIF` in the operator environment; both Compose
profiles honor that setting. Keep the previous SIF and its deployment settings
for recovery. Do not overwrite a runtime used by an active deployment.

Readiness now runs a read-only audit of the requested resources/executables,
including the pinned TFBS validation checksum, followed by the tool's
`--check-prereqs` under the normal network/mount/PID isolation. Missing resources
make the plant capability unavailable; they never cause flags to be silently
dropped. A successful prerequisite check is not end-to-end scientific validation.
The full profile must be exercised against retained real inputs before acceptance,
including tool modules that may catch their own runtime errors.

Profile and SIF identity must match before detector outputs can be reused. Old v2
runs remain v2 when inspected or archived and cannot satisfy a v3 run. Record merges
reject mixed profiles. Genome retrieval caching remains a separate identity.
Summary search status for v3 is `requested`, not an unsupported claim of completed
searches; actual hits are parsed only from plantiSMASH report data. Retained v2 results
continue to say that similarity searches were not run.

## Explicit preparation

On Linux amd64, build the complete worker image from `Dockerfile.worker`. It
installs the official non-setuid Apptainer 1.5.5 package, checksum
`25095d3711504b3e8657dbb2e172ef8db9db43c4503d940c9c36b105db8dce77`.
The installation script verifies those bytes before installation.

Prepare plantiSMASH on the operator host, where Docker is available:

```bash
docker build -f Dockerfile.worker -t clusterweave-worker:local .
python3 bin/prepare_plantismash.py \
  --worker-image clusterweave-worker:local \
  --software-root "$PWD/prepared-software" \
  --cache "$PWD/preparation-cache" \
  --attempts "$PWD/preparation-attempts"
```

Use an operator-owned location outside the checkout for large caches and
attempts in a maintained installation. The command downloads checksum-bound
public inputs, builds offline against a pinned Ubuntu base, packages with
non-setuid Apptainer, and verifies the final SIF before atomic promotion. It
requires no private runtime file. Failed downloads/builds remain in the cache
or attempt directory for diagnosis. Retry the same command after correcting
the failure; verified downloads are reused. An existing matching SIF is checked
and reused. A different existing SIF is preserved and causes a clear refusal;
choose a new software root rather than overwriting it.

The operator helper preserves at least 30 GiB free and requires a prospective
36 GiB allowance for acquisition, staging and image construction. It monitors
build storage and retains failure receipts. It retires only its own unreferenced
temporary builder stage, recording identities and history. Packaging separately
bounds the image export at 8 GiB and unpacking in a 12 GiB temporary filesystem
inside a 20 GiB container. The final SIF and export use disk. Lower-level recipe
commands require the operator to provide the same measured headroom.

The accepted extras SIF SHA256 is
`91b31f064585370abd1eff3f845c8cecf84537ad57b07bb2fd611137d6825679` and its profile SHA256 is
`f8bce449f75d78eddb5d9a15faf95de73625c9936af41d3e7faa52f7949dd0d3`. The historical reduced-profile source-build SIF
`288660c80d58743b6415931d3a891b2213d9f1aff90dafb4def3e805bb991a46` and original legacy SIF
`6c057b048752333a1860a1dcbcd9a44b285b7f4717c8e705f0b10215a5522406` remain historical identities; they cannot execute
the current extras profile. Reading their preserved outputs retains their original
profile and findings.

The new SIF passed immutable positive/empty tool runs, the retained complete
Populus input, and a fresh mixed-output BiG-SCAPE, summary, Clinker, figure and
package replay. Original sequence/CDS identities and spliced domain mappings
were checked independently. This bounded validation does not establish broad
biological accuracy or identity to an external pre-calculated result. Independent
complete-build byte reproducibility has not been established for this new SIF.
The fixed packaging epoch and exact checksum reject a differing rebuild instead
of silently adopting it. See
[`runtime.lock.json`](../software/plantismash/runtime.lock.json),
[`sources.lock.json`](../software/plantismash/sources.lock.json), and
[`resources.lock.json`](../software/plantismash/resources.lock.json).

Preparation needs HTTPS access to the locked upstream package URLs, the pinned
Ubuntu registry image when absent, and worker-image dependencies during its
build. Actual public accession retrieval separately needs NCBI HTTPS access.
Plant analysis uses a network namespace with no external interface.
Jobs never download or replace the SIF or its engine.

## Worker configuration

Mount the prepared software at `/data/software`, with the SIF at
`/data/software/plantismash/plant.sif`. An unset `PLANTISMASH_SIF` uses
`$CLUSTERWEAVE_SOFTWARE_ROOT/plantismash/plant.sif`. An explicitly configured
missing or mismatched asset fails checking. Capability discovery and actual
execution use the same identity and execution checks.

Shared Linux hosts use the [confined SIF profile](CONFINED_SIF.md). Standard
Docker seccomp/AppArmor restrictions can block nested Apptainer even when
unprivileged user namespaces are enabled. The confined profile supplies a
scoped policy and the measured FUSE device; it grants no Docker socket to jobs.
Do not use privileged or unconfined containers or disable the readiness check.
The trusted local Docker profile remains a separate deployment choice.

The readiness check audits the default profile and executes prerequisite
checks in the exact SIF with user, mount, PID and network isolation. A passing
check establishes prerequisites, not successful BGC detection or extra analyses. Inputs bind read-only and each execution attempt has
its own writable output directory. A retry retains the previous attempt and
moves its comparison inputs out of active results. Complete output validation
must pass before calls or downloads are published. Successful empty detection
is distinct from unavailable execution, a failed process or incomplete output.
Retained outputs are labeled as retained, and receipts preserve the recorded
runtime identity instead of assigning them the current runtime's identity.

## Source and notices

The build preserves upstream notices and provides the modified plantiSMASH
source at `/assets/third-party/plantismash-source.zip` on the web service.
Source availability and runtime distribution
are covered in [third-party notices](../THIRD_PARTY.md#pinned-supplied-cds-plantismash-source-build).
The pinned Python 3.8 environment is isolated for tool compatibility; dependency
changes require validation.

## Record parallelism

The canonical annotation/detection runner applies its bounded detector record
parallelism and per-shard CPU allocation to supplied-CDS plantiSMASH as well as
antiSMASH. Whole original records are the unit of work; no chromosome windows
are cut and no supplied gene or protein is rewritten. All per-record runs must
exit successfully and pass original-to-output identity validation before a complete
per-genome result is assembled and passed to the existing BiG-SCAPE staging and
downstream pipeline. Failed or missing shards remain failed/unknown. Records
without CDS remain explicitly not evaluated.

The outer completion schema `clusterweave-plant-record-merge-v1` identifies a
ClusterWeave assembly and retains each per-record execution receipt, exact original
record, tool report, archive and command. It does not claim one whole-genome
plantiSMASH invocation. E-values retain their per-record search-space context;
they can differ from an unsharded search even when domain bit scores and cluster
calls agree. Record splitting preserves the selected profile, producer, rules and thresholds.
Serial/sharded equivalence evidence must state its tested scope.
