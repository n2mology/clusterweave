# Versioned accession-result cache

ClusterWeave can reuse a frozen public accession snapshot and its completed
annotation and BGC detection. The cache is disabled by default. Its contracts cover:

- Feature-free bacterial GenBank preparation, its record map, and record IDs.
- Header normalization of existing fungal GenBank annotations with complete CDS
  translations, when the helper runs in the Docker worker.
- Frozen NCBI retrieval snapshots, including the acquired sequence, available
  annotation, and public assembly metadata.
- The complete per-genome prepared/annotated GenBank, antiSMASH outputs, bacterial
  record map, and applicable FunBGCeX outputs in the Docker worker. This includes
  fungal funannotate annotation when the pinned prepared runtime is selected.

BiG-SCAPE and downstream comparisons, rankings, networks, cohort reports and
packaging run for each job. Logs, job records, access credentials and cohort
results are never shared. Uploaded genomes, unversioned accessions, routes without
authoritative accession provenance, custom execution helpers, external annotation
evidence, and unsupported runtimes compute normally.

Detection contract v3 separates scientific compatibility from scheduling.
CPU allocation, concurrent genomes/records, FunBGCeX's concurrent-genome worker
count and container resource limits are recorded as execution provenance rather
than cache-key parameters. Each FunBGCeX invocation receives one genome file.
CPU settings for an annotator that actually runs, numerical-library threads,
seeds and scientific options remain identity-bearing until their equivalence is
established. Unused annotation CPU budgets do not invalidate existing-CDS results.

Stable multi-record inputs always use the same per-record antiSMASH partition,
including when only one shard runs at a time. Partition/output policy is versioned
in the key. Single-record inputs and unstable record identifiers retain their
defined whole-input handling. Changing concurrency does not change that policy.
Older v2 detection entries remain under their original identities; they are not
automatically migrated or claimed compatible. Retrieval snapshot contract v2 is
unchanged, so this change does not itself require downloading genomes again.

Normal jobs reuse the exact stored retrieval snapshot until it expires, is evicted,
or an operator explicitly invalidates it. This avoids downloading the same genome
for every job. An accession version is a lookup identifier; the stored snapshot
manifest freezes the actual acquired bytes. Cache reuse does not promise that a
later NCBI download or an independent scientific-tool execution is byte-identical.
Tool timestamps and execution paths can differ even with pinned dependencies.

## Identity and validation

An eligible route must contain exactly one matching genome record, use the
`ncbi` source, and identify the same versioned `GCA_` or `GCF_` assembly in both
`input_key` and `source_accession`. The selected acquired source file must be
inside the routed genome input directory. Accession versions remain distinct.

Each key is the SHA-256 digest of canonical JSON containing:

- The normalized accession and SHA-256 digest of the acquired source bytes.
- The taxon and exact preparation route.
- The preparation source closure, including the runner and validators.
- Installed Python executable, standard-library contents, loaded native libraries,
  and, for fungal preparation, Biopython and NumPy contents where loaded.
- The cache schema and the versioned output contract.
- All preparation arguments that affect output: genome-label digest and bacterial
  minimum and maximum record lengths.

The two preparation contracts use no separate scientific container, database, or
model and record `not-used` for these fields. The retrieval contract identifies the
exact NCBI CLI and unzip binaries, Python runtime, downloader source and include policy; its
request digest identifies the versioned accession, and its manifest identifies
the acquired snapshot bytes. The annotation/detection contract additionally pins
the prepared native runtime contents, scientific sibling image IDs, complete antiSMASH database
content, embedded models/databases, scientific producer source, accession
input inventory, taxonomy/mapping and scientific/resource parameters. Sibling
tools execute by their recorded image IDs. Native fingerprints include installed
code, executables, libraries, data and loader configuration. Derived Python bytecode
caches are excluded when their source exists. File modes are included; timestamps
serve as mutation guards. Mutable tags or version labels alone
never establish compatibility. Missing external annotation identities cause misses.

The current retrieval contract is version 2 and detection contract is version 3. Cache storage and
validation code are separate from scientific producer identity. A cache-only fix
does not invalidate completed biology when native runtime contents, scientific
source, inputs and parameters remain identical. Each detection bundle records its
original worker image and verified native/source identities; fresh job provenance
also records the worker that materialized it. Service image IDs alone never
establish native-runtime equivalence. Unsupported older records miss unless their
complete original execution evidence is independently verified.

Volume names and absolute host paths are excluded from content identity. A worker
must still have the configured shared store mounted; ClusterWeave does not scan
other job directories or arbitrary volumes. Older completed jobs without complete
provenance cannot be imported merely because their accession matches.

Missing, unknown, unsupported, unreadable, or changing identities produce misses.
Changing source bytes, installed runtime code, assembly version, route, or relevant
arguments invalidates reuse. File timestamps never establish compatibility.
The cache reads fixed files or a bounded, validated biological bundle. It verifies manifest schema, canonical
identity, file inventory, sizes, SHA-256 digests, GenBank structure, and related
record maps before reuse. Additional checks reject execution paths and credential
markers in copied metadata. The exact public SGD homepage reference found in
NCBI yeast GenBank comments is accepted; extended URLs, private paths, and
credential markers still cause misses. Public origin comes from authoritative routing;
text checks alone cannot establish that origin. Public library UUIDs are allowed;
the actual job identifier and private execution paths are rejected. Bundle validation rejects traversal,
links, duplicate members, excessive decompressed sizes, other accession labels,
partial or failed detector outcomes, invalid GenBank and missing fungal translations.

## Storage and ownership

An operator must explicitly provision a separate filesystem or directory, owned
by the worker account with mode `0700`, and set
`CLUSTERWEAVE_ACCESSION_CACHE_ROOT` to its absolute path. Provisioning storage is
an operator action. ClusterWeave does not create the root or mount a cache volume
in the shipped Compose profile. Do not put the cache inside the repository,
job-data volume, acquisition tree, uploads, or result directories. Cache storage settings are operator-only and cannot be changed through raw job
environment overrides. The web service and scientific child containers do not
need access to this store.

The root contains `entries/`, `quarantine/`, bounded claim files, and a private
advisory lock. Entries use digest names and contain biological files or a portable
bundle plus `manifest.json`. Retrieval entries contain public acquired inputs;
detection entries contain accession-local outputs. Execution paths are replaced
with reserved path markers and reconstructed for the new job. Scientific data and
public accession identifiers are retained. Prior job identifiers, records,
result-access credentials, logs, and cohort results are excluded.
The worker account and operator are trusted; this store does not defend against
an account that can replace application code or acquired public input bytes.

A short nonblocking filesystem lock serializes entry operations. Busy metadata
operations can miss safely. Retrieval and complete annotation/detection also hold
an identity claim across lookup, computation and population, so concurrent matching
jobs normally reuse the first completed result. There are 256 claim slots; a slot
collision only serializes unrelated work. Waiting checks cancellation and is
bounded to one hour, after which ordinary computation remains available. The
lighter preparation adapters can duplicate preparation on concurrent misses.
Matching writers retain the existing entry. Conflicting outputs
for one identity quarantine the existing entry and reject the new population.

Publication writes and synchronizes a private staging directory, then atomically
renames it into `entries/`. Failed or interrupted work is never promoted.
A later lock holder removes abandoned staging directories. Hits copy verified
bytes into new job files without hard links or symlinks. Job files remain mutable
and independent. Corrupt entries move to quarantine and normal computation
continues. Quarantine is bounded by the same capacity and retention policy.
Cancelled, partial, failed and previously staged job outputs cannot populate a
complete detection entry. Native non-Docker and BRAKER/evidence routes retain
normal computation until they have a complete supported dependency contract.

The defaults are 10 GiB, 256 entries including quarantine, and 30 days of retention.
Operators can set positive integer limits with:

| Variable | Meaning |
| --- | --- |
| `CLUSTERWEAVE_ACCESSION_CACHE_MAX_BYTES` | Total declared entry bytes, including manifests and quarantine |
| `CLUSTERWEAVE_ACCESSION_CACHE_MAX_ENTRIES` | Maximum entry and quarantine count |
| `CLUSTERWEAVE_ACCESSION_CACHE_MAX_AGE_SECONDS` | Maximum age since population |

Cache retention is independent of job retention. Deleting a job does not delete
shared cache entries, and cache eviction does not remove a job's materialized
results. Cleanup is demand-driven rather than a separate scheduled recycler.
An idle cache can retain expired files until the next lookup, publication or
operator inspection; expired entries cannot produce a hit. Normal computation
repopulates eligible results after eviction.

Limits are enforced during lookup, publication, and inspection. Expired entries
are removed first. Capacity pressure removes quarantine before the oldest live
entries. Hits do not extend retention. Oversized entries are not populated.
Each biological bundle is limited to 512 MiB decompressed and 20,000 files.
Filesystem overhead is additional; provision free space beyond the byte limit.
If the filesystem fills, preparation still succeeds through normal computation.

## Provenance and recovery

Job provenance is written under
`reproducibility/accession_cache/`. Separate retrieval, preparation and detection
records identify their boundary. Each records hit or miss,
validation outcome, population status, accession, key, canonical identity, and,
for hits, the verified entry manifest. Shared manifests contain no host paths
or identifiers for earlier jobs. Unknown identities are never filled in from
an accession filename or another job.

Set `CLUSTERWEAVE_ACCESSION_CACHE_FORCE_MISS=1` to bypass both lookup and
population. The existing `FORCE=1` setting and annotation runner `-f` option also bypass the cache. Removing
`CLUSTERWEAVE_ACCESSION_CACHE_ROOT` restores ordinary preparation. Neither action
changes existing job results or requires a migration. A forced job neither reads
nor replaces the frozen snapshot. To refresh the shared source, invalidate its
exact retrieval entry, then let a normal job acquire and populate a new snapshot.
The new input digest automatically selects a different detection entry if the
source bytes changed.

With the cache environment set, run these commands from the source root in the
worker's Python environment:

```bash
python3 bin/cached_genbank.py inspect
python3 bin/cached_genbank.py delete --key <exact-64-character-key>
```

Inspection and deletion use the store lock. Inspection applies retention and
capacity cleanup. Back up a quiescent store while workers are stopped; restore
it into a separate directory with the same ownership and permissions. Restored
entries are validated on use. The cache is disposable and ordinary recomputation
is the recovery path. Do not restore job data or access credentials into it.

Before enabling the cache, operators should verify the configured storage,
exercise a bounded public-accession hit and miss, and retain a recovery plan.

## Exact availability catalog

The cache maintains a disposable SQLite metadata index. It contains versioned
accessions, existing scientific identity keys, contracts, input/source/runtime
digests, manifest digests and lifecycle timestamps. Scientific payloads remain in
the separate validated store. The index contains no job identifiers, owners,
credentials, execution paths or logs. Volume paths are not scientific identity.

In a web/worker instance, the worker writes the index to
`DATA_DIR/worker/accession-cache/catalog.sqlite`. The web service reads this
metadata with a read-only SQLite connection; it does not mount the scientific
cache. A standalone CLI without DATA_DIR uses `catalog.sqlite` inside the
operator's configured cache root. Directories require owner-only access and
database files require owner-only regular files without links. SQLite connections,
queries and metadata inventories are bounded. This design supports a single
host; cross-host workers should use a catalog service rather than sharing a
SQLite file over an arbitrary network filesystem.
DATA_DIR is an operator setting and cannot be redirected through raw job
environment overrides, including administrator submissions.

The worker reconciles metadata every 30 seconds while the cache is configured.
Publication, deletion, quarantine and retention operations also update the index.
Metadata writes run outside scientific preparation processes so loading SQLite
does not change their native-library identity. Indexing failures do not change
cache hits, scientific results or normal recomputation. A committed entry can
temporarily be absent from the index after interrupted indexing. Reconciliation
repairs this from authoritative manifests without running scientific tools or
importing older results. Cache lookup always consults and validates the actual
store, including when the index says an accession is absent.

Availability is advisory. `candidate_available` means a current entry is indexed;
the worker still checks exact identity, policy, checksums and biological structure
before copying it. Supply an exact scientific key to distinguish a matching
candidate from `incompatible` variants. Without that key, an accession match does
not establish compatibility with the submitted configuration.

Other states are `in_progress`, `legacy_unverified`, `population_failed`, `expired`,
`quarantined`, `absent` and `unknown`. Historical inventory records only eligible
public accession membership from successful jobs lacking current detection
provenance. It never assigns current tool identities to older outputs or makes
them reusable. New publication failures retain bounded reason codes such as
`store_busy`, `payload_map` or `storage_error`; older generic failure records
remain generic. Inventory is bounded to 1,024 job directories, 256 records per
job and 16,384 indexed identities. Partial inventory, a missing/corrupt catalog,
or a catalog not reconciled within 90 seconds cannot establish absence. Large
variant lists are bounded and explicitly marked as truncated.

An operator can refresh the index and query it in the worker environment:

```bash
python3 bin/inspect_accession_cache.py refresh
python3 bin/inspect_accession_cache.py query --accession GCF_000005845.2
python3 bin/inspect_accession_cache.py query --accession GCF_000005845.2 --stage retrieval
python3 bin/inspect_accession_cache.py query --accession GCF_000005845.2 --key <exact-64-character-key>
```

Refresh changes derived metadata only. A corrupt index can be moved aside by the
operator while metadata writers are stopped, then rebuilt with `refresh`. Preserve
the scientific entries and their manifests. No Bloom filter is used.

## Catalog access control

`POST /api/cache/availability` requires an explicitly configured administrator
credential in a supported authentication header, or an authenticated local-owner
browser session with CSRF validation. The hosted profile never pairs local owners.
The trusted local profile's implicit administrator access does not apply to this
endpoint. Local operators can use the filesystem CLI without an HTTP credential.
The request body accepts only `accessions`, optional `stage` (`retrieval`,
`preparation` or `detection`), and optional `keys`, mapping requested accessions to
their exact scientific keys. Requests accept at most 50 explicitly versioned
accessions and 16 KiB of JSON. For example:

```json
{"accessions":["GCF_000005845.2"],"stage":"detection"}
```

The response contains `advisory: true`, its reconciliation timestamp and bounded
candidate metadata. Missing or stale catalogs return HTTP 503 with status
`unknown`; normal verified cache lookup remains available. Unknown request fields,
unversioned accessions and unsupported stages are rejected. There is no public
catalog listing or HTTP mutation endpoint. Submission credentials and job read
tokens do not grant global availability access.

`GET /api/results/<public-run-id>/cache` requires that job's read token or an
explicit administrator credential, including in local mode. It returns only that
job's accession, stage, contract, hit/miss, bounded reason and population status.
`identity_recorded` distinguishes a saved requested identity from an older rejected
attempt that recorded only its public accession route. Such an older rejection
does not establish scientific compatibility or authorize reuse.
Raw manifests, keys, paths, producer-job relationships and execution metadata are
excluded. Anonymous requests, other jobs' read tokens and submission credentials
receive the same generic not-found response. Missing records are reported as
`not_recorded`; incomplete metadata is explicitly marked.

Both endpoints authenticate before metadata access, use no-store responses, and
limit each authenticated principal to 30 requests per minute with two concurrent
metadata operations per web process. Requests beyond those bounds return HTTP 429.
Audit messages identify the operation, role and item count without credentials or
query bodies. These process-local limits supplement operator ingress controls;
multiple web processes require an aggregate rate limit at the hosting boundary.
Public scientific entries remain shareable internally. Uploads, private tenant
data and other jobs' provenance remain outside global reuse and disclosure.

## Progress labels

The web BGC Workflow station and CLI tree show **CACHED** after annotation and detection are restored from a validated complete result. **GENOME DOWNLOADED** identifies fresh retrieval. **GENOME READY** identifies an available input awaiting annotation and detection. Fresh analysis proceeds through **ANNOTATING**, **DETECTING** and **COMPLETE**. BiG-SCAPE and downstream stages continue with their own progress after each genome is ready.
