# Extending ClusterWeave

This guide follows a contributor change from configuration and input validation
to scientific execution, result readers, figures and downloadable packages.
Start with [Architecture](ARCHITECTURE.md) for the service boundaries and
[Beginner setup](BEGINNER_SETUP.md) to install a local instance. Installation
commands remain in the beginner and [technical installation](INSTALL.md) guides.

A biosynthetic gene cluster (BGC) is a predicted group of neighboring genes.
BiG-SCAPE groups related BGC records into gene cluster families (GCFs). An
extension is complete when its intended users can prepare its dependencies,
select it through the supported interface, interpret its outcomes and recover
its declared outputs outside the original job.

This source supports fungal and bacterial routes and supplied-CDS plantiSMASH
routing for annotated green-plant GenBank. `analysis_scope=both` means fungi plus
bacteria; `plants` and per-genome `mixed` routes are explicit. See
[Supplied plant annotation](PLANT_INPUTS.md) for admission, prepared-runtime and
scientific scope limits. Funannotate2 and Tiberius remain outside these profiles.
The extension examples do not establish scientific suitability.

- [Follow a job through the source](#follow-a-job-through-the-source)
- [Choose the extension boundary](#choose-the-extension-boundary)
- [Keep taxonomy and model identities separate](#keep-taxonomy-and-model-identities-separate)
- [Update a genome annotator](#update-a-genome-annotator)
- [Add a BGC detection tool](#add-a-bgc-detection-tool)
- [Add or update a figure tool](#add-or-update-a-figure-tool)
- [Prepare and check a local instance](#prepare-and-check-a-local-instance)
- [Validate the change you made](#validate-the-change-you-made)
- [Package, migrate and recover](#package-migrate-and-recover)

## Follow a job through the source

The root shell scripts are supported entrypoints. Sourced annotation and
detection modules depend on their runner's variables and functions; they are
not standalone command-line tools or a plugin registration API.

```text
browser -> web validation -> frozen route/settings -> job store -> worker
                                                           |
CLI preparation -------------------------------------------+-> inputs
                                                               |
                      run_clusterweave.sh: annotation/detection
                           -> BiG-SCAPE -> summary -> clinker
                                                               |
                      web orchestration or explicit CLI follow-ups
                           -> figures / optional analyses
                                                               |
                      readers -> public policy -> reports / package
```

| Boundary | Current source and responsibility | What the next consumer needs |
| --- | --- | --- |
| Configuration and submission | [app.py](../web/app.py) validates uploads, accession metadata, permissions and runtime requests; [clusterweave.js](../web/static/assets/clusterweave.js) presents the input station. [defaults.env](../config/defaults.env) documents shell configuration; runner environment defaults and [canonical_pipeline.py](../web/canonical_pipeline.py) `_base_env` determine actual execution settings. | Accepted settings, authoritative route rows and available capabilities. A shell environment option is not automatically exposed in web requests or passed through Compose. |
| Taxonomy and profiles | [taxon_routing.py](../web/taxon_routing.py) `build_taxon_routes` owns validation and authority; [scientific_profiles.py](../web/scientific_profiles.py) projects `default_prediction_method`, `default_detector_profile` and applicability counts for already validated taxa. | Immutable input/genome identity, taxon source, prediction method and detector profile. An enum or dropdown addition alone is insufficient. |
| Queue and execution | [job_store.py](../web/job_store.py), [worker.py](../web/worker.py) `process_one`, [resource_policy.py](../web/resource_policy.py), [stage_runner.py](../web/stage_runner.py) and [slurm_backend.py](../web/slurm_backend.py) manage jobs, admission, child processes and the external executor. | Isolated job paths, bounded CPU/memory use, cancellation and truthful terminal state. |
| Input preparation | [prepare_genomes_from_accessions.sh](../prepare_genomes_from_accessions.sh) and [scripts/ncbi/](../scripts/ncbi/) acquire declared inputs; canonical `_stage_uploaded_inputs` and `_write_taxon_manifests` stage uploads and route metadata. [annotation_input.py](../bin/annotation_input.py) reads the shell route contract. | Explicit fungal, bacterial and plant roots and a canonical genome manifest. A supplied empty manifest must not turn into discovery of unrelated genomes. |
| Annotation and detection | [run_annotation_and_detection.sh](../run_annotation_and_detection.sh) coordinates `prepare_annotation_tooling`, `prepare_genome_genbank`, detector calls, resource planning and per-genome manifest rows. The owners are listed below. | Usable staged GenBank, detector outputs, maps and actual success, exclusion, failure or reuse evidence. |
| Grouping and summaries | [run_bigscape.sh](../run_bigscape.sh) stages regions and their crosswalk; [summarize_clusterweave.sh](../summarize_clusterweave.sh) invokes [summarize_clusterweave.py](../bin/summarize_clusterweave.py), whose readers include `parse_antismash`, `parse_funbgcex` and `parse_bigscape`. [build_bgc_gcf_crosswalk.py](../bin/build_bgc_gcf_crosswalk.py) and [gcf_view.py](../bin/gcf_view.py) connect regions to family views. | Stable producer/genome/record/region ownership, selected grouping inputs, tool outputs and unassigned records. Similar filenames do not establish equivalent formats. |
| Selection and figures | [build_candidate_tables.py](../bin/build_candidate_tables.py), [export_dataset_family_atlas.py](../bin/export_dataset_family_atlas.py), [export_priority_shortlist.py](../bin/export_priority_shortlist.py), [export_shared_family_shortlist.py](../bin/export_shared_family_shortlist.py) and [stage_clinker_panels.py](../bin/stage_clinker_panels.py) feed [run_clinker.sh](../run_clinker.sh). [run_figures.sh](../run_figures.sh) renders declared tables and grouping outputs. | Exact joins back to the tool record, explicit taxon applicability, labels, missing-data semantics and portable panel inputs. |
| Reports and delivery | [researcher_report.py](../web/researcher_report.py) writes methods/provenance; canonical `_collect_result_files` creates the manifest and ZIP. [result_policy.py](../web/result_policy.py) admits paths, [public_results.py](../web/public_results.py) builds the artifact catalog and [result_attestation.py](../web/result_attestation.py) binds completed results. | Allowlisted files, checksums, correct package paths, producer/version evidence and authenticated access. Files written to disk are not automatically browser results. |

`run_clusterweave.sh` executes four core stages: annotation/detection,
BiG-SCAPE, summary and clinker. The web `run_pipeline` prepares inputs first,
then invokes that wrapper, figures and selected follow-ups, and finally
packages results. Direct CLI users invoke preparation and follow-up entrypoints
explicitly with the same project paths and intended environment. The wrapper
alone does not execute every stage shown in the web interface. The wrapper
does not automatically source `config/defaults.env`; standalone callers supply
exported environment settings. Web jobs use the accepted settings translated
by `_base_env`, subject to the web submission policy.

## Choose the extension boundary

Use the existing owner for an update. For a new tool, add the smallest concrete
adapter and reader needed by its real input/output contract. There is no generic
plugin registry, automatic schema negotiation or automatic public exposure.

| Category | Entrypoints and owners | Applicability and configuration | Runtime, assets and identities |
| --- | --- | --- | --- |
| Genome annotator | [annotation_prepare.sh](../annotation_prepare.sh): `prepare_genome_genbank`, `annotate_genome_with_fallbacks`; [annotation_funannotate.sh](../annotation_funannotate.sh): `resolve_funannotate_policy`, `run_funannotate_predict_to_gbk`; [annotation_braker3.sh](../annotation_braker3.sh): `run_braker3_to_gbk`; [annotation_runtime.py](../bin/annotation_runtime.py): scientific argv builders. | Reuse usable fungal CDS before prediction. `ANNOTATION_FALLBACK_ORDER` defaults to `funannotate`; BRAKER3 needs explicit enablement and evidence. Bacteria retain feature-free input and Prodigal through antiSMASH. Web annotation choices are filtered separately. | Prepared host, Docker and SIF execution, exact executable/image/model/evidence identities and per-job output paths. The funannotate recipe prepares its BUSCO datasets; readiness does not demonstrate model accuracy. |
| BGC detection tool | [detection_antismash.sh](../detection_antismash.sh): output validation and `run_antismash_sharded`; [detection_funbgcex.sh](../detection_funbgcex.sh): `run_funbgcex_cli`, `run_funbgcex_detection`, `funbgcex_outputs_valid`; [detection_plantismash.sh](../detection_plantismash.sh) handles supplied-CDS plant detection; runner `compute_genome`. | antiSMASH applies to supported fungal/bacterial routes; FunBGCeX applies only to fungi; plantiSMASH requires supplied translated plant CDS. Profile defaults, intake validation, manifest readers and downstream applicability must agree. | Prepared runtime plus exact rules/HMMs/databases and effective settings. Keep tool producer identity distinct from derived grouping representations. |
| Figure tool | [run_figures.sh](../run_figures.sh): `render_taxon_bigscape_multipanel` and output-readiness functions; [render_bigscape_multipanel.py](../bin/render_bigscape_multipanel.py): `render_multipanel`; [render_bigscape_network.py](../bin/render_bigscape_network.py), [render_bgc_overlap.py](../bin/render_bgc_overlap.py), [render_phylo_taxon_profile.py](../bin/render_phylo_taxon_profile.py). | Read declared summaries/crosswalks; preserve fungal/bacterial applicability. `RUN_BIGSCAPE_MULTIPANEL_FIGURE`, `RUN_TAXON_TREE_FIGURE`, format and canvas options select presentation. | Worker Python; optional CairoSVG for raster exports, R for the optional summary renderer. Record relevant rendering dependencies separately from annotation models and detector databases. |
| Optional analysis | [run_phylogeny.sh](../run_phylogeny.sh), [prepare_phylogeny_families.py](../bin/prepare_phylogeny_families.py), [run_integrated_evidence.sh](../run_integrated_evidence.sh), [run_nplinker.sh](../run_nplinker.sh), with canonical `run_pipeline` dispatch. | Sequence inference and cross-kingdom evidence are disabled by default and require authorized web settings. NPLinker needs its selected data/target. Each stage defines whether failure is fatal. | Prebuilt phylogeny runtime or prepared NPLinker environment; explicit bounds, assets, versions and input manifests. Scientific input acquisition is distinct from runtime installation. |

| Category | Output, provenance and failure contract | Consumers, caches and compatibility | Exposure, packaging and validation work |
| --- | --- | --- | --- |
| Genome annotator | Staged translated GenBank, source-to-tool record mapping and actual producer; retain failed attempts and excluded genomes. Presence of translations is a readiness check, not proof of correct sequence translation or gene structure. | Both detectors consume annotation; changed genes can change regions, GCFs, selected panels and exports. Reconcile preparation and detection cache source closures; retain old producer/result readers. | Connect CLI/web settings, preparation, capabilities, observed versions and worker COPY/imports. Test reuse, taxonomy/model routing, conversion, failures and cancellation; require independent scientific evidence for changed predictions. |
| BGC detection tool | Validate complete tool output before success; distinguish genuine zero from failed, missing, inapplicable and retained output. Preserve original, tool and derived record mappings. | Add tool-specific readers, grouping staging, crosswalks, selected-GCF consumers, figures and downloads. Existing cache contracts recognize specific tools and payload shapes, not arbitrary directories. | Add capability/configuration and precise result allowlists, browser categories, citations and portable exports. Test tool-to-consumer joins, empty/failure/corruption states and actual runtime behavior; assess scientific applicability separately. |
| Figure tool | SVG/tables/GraphML and requested supported raster outputs; preserve counts, identities, legends and unavailable values. Inspect actual outputs because some renderer failures are warnings. | Figures are regenerated from job-specific data, outside accession detection reuse. Existing-file readiness checks may skip rendering unless refreshed. Changed names/formats need consumer compatibility. | Check web collection, artifact categorization, ZIP contents and copied helper dependencies. Test layout, long labels, empty/sparse/cohort cases and exports. A layout-only change needs no annotator benchmark. |
| Optional analysis | Bounded input manifest, outputs and measured status/provenance. Optional phylogeny/evidence can retain core success; selected NPLinker currently uses a required-stage call and may fail the job. | Verify selected-family/data joins and applicable public result policy. Do not reuse unrelated accession outputs as a cohort-level analysis. Preserve disabled and unavailable states. | Update runtime admission, authorized settings, resource/cancellation handling, reports, packages and any generated commands. Test optional-versus-required behavior and migration; scientific changes need their own suitability evidence. |

For all four categories, use the migration and rollback procedure below when
changing an existing interface. Do not reinterpret an old option silently or
start a deprecation period merely by documenting a proposed replacement.

## Keep taxonomy and model identities separate

NCBI taxonomy governs accession routes. Uploaded authoritative GenBank taxonomy
and explicit assignments are resolved by `build_taxon_routes`; conflicts are
rejected. Shared profile helpers do not validate new taxa. They must only receive
supported, validated groups.

The current funannotate owner reads the genome mapping and resolves an organism
label plus a BUSCO dataset. Its automatic dataset policy recognizes Mucorales,
Mucoromycota, Microsporidia, Ascomycota, Basidiomycota, Dikarya and broader fungal
metadata. Explicit missing datasets fail; an unavailable automatic selection may
warn and use the configured installed fallback. Missing taxonomy uses the
configured no-taxonomy/default path. These are implemented compatibility rules,
not evidence that every fallback is scientifically suitable.

| Identity | Current behavior or contributor evidence required |
| --- | --- |
| Authoritative organism | Retain taxid, lineage, source accession/assembly and species/strain metadata. The legacy organism label can be reduced to a binomial or inferred from a genome label when metadata is missing; that label is not an independently validated taxonomic assignment. |
| BUSCO training dataset | `FUNANNOTATE_BUSCO_DB` selects the legacy dataset passed as `--busco_db`. Preserve its exact installed content and version. Legacy dataset names are not aliases for a newer annotator's database interface. |
| Evaluation dataset | Identify the separately selected evaluation lineage/version and any overlap with training. A training BUSCO score is not independent held-out accuracy. |
| Initial AUGUSTUS model/configuration | `FUNANNOTATE_BUSCO_SEED_SPECIES` optionally supplies `--busco_seed_species`. It is unset by default. Current taxonomy-based BUSCO selection does not automatically establish a taxonomy-specific AUGUSTUS species-model selection. Record the actual initial model and configuration hashes for any new route. |
| Generated training parameters | Retain per-genome training inputs, evidence, parameter files and identities. Keep writable training state isolated between jobs. A generated model is distinct from its initial seed. |
| Model consumed by prediction | Verify actual prediction arguments and referenced parameter bytes. A species label, installed dataset, successful training step or output directory does not prove which model prediction used. |

`funannotate_predict_argv` and `braker3_argv` in `annotation_runtime.py` remain
the argument-construction boundary. Do not add an independent command builder
in the web service. A future annotator with separate training and prediction
commands needs explicit adapters for those commands and their provenance.

Preserve the existing upstream 200-training-model criterion and the qualified
150-model retry policy when making a non-scientific change. Changing thresholds,
evidence, fallback eligibility or model selection changes the scientific method.
Test missing/conflicting taxonomy, explicit overrides, unavailable assets,
representative fungal groups and job isolation before claiming a new route.

## Update a genome annotator

Worked route: update the existing funannotate integration. This is a contributor
procedure, not a command sequence that installs a replacement.

1. Identify whether the change affects dispatch only, dependencies, input
   conversion or scientific predictions. Start at `run_funannotate_predict_to_gbk`
   and `funannotate_predict_argv`. Keep the host, Docker and SIF adapters consistent
   with the supported backend being changed.
2. Follow `prepare_genome_genbank` from ready staged CDS to original supplied CDS
   and then the configured fallback chain. Keep the existing reuse decisions,
   bacterial policy and separately enabled BRAKER3 evidence route intact.
3. Trace the six identities above. Update preparation in
   [prepare_runtime.py](../bin/prepare_runtime.py) and the relevant
   [funannotate recipe](../software/funannotate/) only when dependencies change.
   `RuntimePreparer.prepare` may acquire assets; `RuntimePreparer.check` verifies
   them. A job must not install its missing runtime.
4. Follow the tool’s GenBank and any conversion through
   [annotation_genbank.py](../bin/annotation_genbank.py),
   [gff3_to_gbk_with_translations.py](../bin/gff3_to_gbk_with_translations.py) and
   [genbank_readiness.py](../web/genbank_readiness.py). Check compound/reverse
   locations, phase, partial CDS, translation tables, isoforms and identifier
   maps. Existing readiness checks do not certify a lossless general conversion.
5. Follow manifest statuses and actual attempted-tool versions into
   `researcher_report.py`, detector inputs, grouping and selected-GCF outputs.
   A failed annotation can exclude a genome; skipped detection must not appear
   as zero BGCs. Preserve tool output separately from any derived conversion.
6. Review `cached_genbank.make_identity`, `cached_accession.source_digest` and
   `cached_accession.detection_identity`, both Dockerfiles, public settings and
   historical result fixtures. New scientific producers require distinct
   identities; a new tool version must not inherit an old producer label.
7. Run focused ownership, lineage, argv, cache and result-reader tests. A changed
   scientific method also needs prospective independent evaluation and actual
   runtime evidence. Document accepted scope, migration and pinned rollback.

Useful starting tests are [annotation ownership](../tests/test_annotation_ownership.py),
[lineage policy](../tests/test_annotation_lineage_policy.py),
[runner contract](../tests/test_annotation_runner_contract.py),
[GenBank readiness](../tests/test_genbank_readiness.py) and
[accession adapters](../tests/test_cached_accession.py). Stubbed dispatch tests
verify software behavior; they do not measure annotation accuracy.

## Add a BGC detection tool

Worked route: add a distinct detector alongside the existing tools. The new
adapter and output format are illustrative; no new detector command is provided
or implied to exist.

1. Define accepted taxa and annotated/sequence input requirements. Trace intake,
   shared profile defaults, shell route loading and `compute_genome` together.
   Never send an unsupported taxon through a generic fungal default. Preserve
   `both=fungi+bacteria`; the shipped `plants` and `mixed` scopes are distinct.
2. Use the existing antiSMASH and FunBGCeX owners as examples of bounded runtime
   dispatch, completion validation and per-genome outcome handling. Keep the
   new detector's output format, version, rules and evidence identifiable.
   Prepare assets explicitly and expose readiness only for an implemented route.
3. Add a reader for that format rather than assuming `parse_antismash` accepts another
   tool's JSON or GenBank. Bind tool records and cluster membership back to
   original sequence/CDS identities. Validate a complete empty result separately
   from missing output, corrupt output and a nonzero exit.
4. Connect the reader to grouping. `run_bigscape.sh` discovers antiSMASH region
   files and explicitly stages plantiSMASH clusters through
   `bin/plantismash_consumers.py`. Other cluster files are not included automatically. If the selected BiG-SCAPE parser needs derived records,
   preserve the tool’s files and record the transformation and selected/excluded
   features. Measure compatibility against the exact runtime, Pfam and MIBiG
   inputs. Do not infer unchanged distances or families from identical proteins.
5. Follow `build_bgc_gcf_crosswalk.py`, `gcf_view.py`, candidate tables, shortlists,
   atlas, clinker staging and figure inputs. Verify unique joins, duplicates,
   unassigned records, taxon applicability and complete versus comparison-selected
   downloads. File creation alone does not prove any of these connections.
6. Extend the actual report and public-result readers, browser categories,
   precise allowlists and portable manifest. Keep raw BiG-SCAPE data separate
   from [sanitized public copies](../web/bigscape_public_db.py). Check the tool’s HTML
   assets under existing access/sandbox rules before offering a report viewer.
7. Establish distinct cache/producer contracts or leave unsupported reuse
   disabled. Verify CLI and web paths, copied runtimes, download extraction and
   rollback. Run a separate scientific evaluation for the declared taxa and
   intended use before advertising accuracy or replacing a supported tool.

Starting regression areas include [FunBGCeX extraction](../tests/test_funbgcex_extraction.py),
[BiG-SCAPE taxon staging](../tests/test_bigscape_taxon_staging.py),
[selected-GCF consumers](../tests/test_selected_gcf_downstream.py),
[zero-region outcomes](../tests/test_zero_region_downstream.py) and
[public result manifests](../tests/test_public_result_manifest.py).

### Preserve record identity through comparison

Track each supplied CDS by source-file checksum, record ordinal and CDS feature
ordinal. Protein IDs, locus tags, coordinates and sequences are attributes;
distinct isoforms can share them. Preserve the one-to-one mapping from original annotation
to detector records, declare identifier normalization, and retain the original
feature key in each cluster crop. Overlapping clusters can refer to the same
feature without becoming one comparison input. Checksums bind source crops and
staged files to their unchanged DNA, proteins and features.

For the pinned BiG-SCAPE 2.0.0-beta.6 parser, `cds.orf_num` is the one-based input
CDS ordinal assigned before overlap filtering. Join on `(gbk.id, orf_num)`, verify
bounds, strand and translation, and require the staged checksum to match
`gbk.hash`. Use the completed engine log to establish the parser version. Missing
translations, duplicate ordinals, conflicting content and unsupported parser
versions are errors; matching proteins alone cannot identify a selected isoform.

The `native-comparison-selection-v2` receipt retains the full CDS inventory and
marks the selected ordinals. BiG-SCAPE's overlap filtering can omit isoforms;
its strict `MIN_BGC_LENGTH < length < MAX_BGC_LENGTH` rule can omit clusters.
Accept a length exclusion only with the completed run, configuration/logs and
checksum-verified cluster file. Record the length, limits and evidence hashes,
set `comparison_status`/`comparison_exclusion`, and leave comparison/public IDs
null. Unexplained absence within the allowed range remains an error. Preserve
the detector's cluster files and calls; do not change cutoffs or sequences to
force a match. Selection does not establish biological importance.

## Add or update a figure tool

Worked route: change the existing BiG-SCAPE multipanel layout while retaining
its scientific inputs and counts.

1. Start at `render_taxon_bigscape_multipanel` in `run_figures.sh`. It passes the
   summary, canonical region crosswalk, taxon manifest, grouping category and
   threshold to `render_multipanel`. Missing clustering or required inputs
   prevent this figure from being produced.
2. Keep `read_summary_rows`, `count_matrix`, `assign_complete_taxon_groups` and
   the network readers consistent with their existing contracts. Change drawing
   and label placement without silently filtering records or reclassifying calls.
   A threshold or membership change requires a different validation scope.
3. Check requested SVG/PNG outputs and optional conversion dependencies.
   Existing output-readiness checks can skip already rendered files; use the
   documented `FORCE=1` refresh only in the intended local result workspace.
   Never overwrite the sole retained scientific result to test a layout.
4. Follow `is_public_analysis_relative_path`, `build_artifact_catalog`, canonical
   `_collect_result_files`, package checksums and browser figure selection.
   New formats or special taxonomy-tree filenames may need explicit admission.
   For a new helper, also connect its runner option, copied dependencies and
   missing-output behavior; there is no automatic discovery.
5. Test fungi, bacteria, mixed cohorts, no clustering, sparse networks, long
   labels, many genomes and missing ecology. Verify that bacteria do not acquire
   a FunBGCeX row. Inspect exported files and browser/package rendering at useful
   sizes. Use the existing [fungal/general](../tests/test_bigscape_multipanel_rendering.py)
   and [bacterial](../tests/test_bacterial_multipanel_rendering.py) rendering tests.

[Reproducibility: Figures](REPRODUCIBILITY.md#figures) lists existing output
names and supported rendering controls. A layout-only change can be checked
with generic retained inputs and rendering tests. It does not require running
annotation or detection again.

## Prepare and check a local instance

Use a Bash-compatible terminal in the repository root on Linux, macOS or the
WSL distribution described in the beginner guide. The browser is a separate
interface. Scientific runtimes run inside the prepared worker/tool environment;
installing a Python package on the host does not prepare those containers.

| Step | Instructions and execution context | Success and next step |
| --- | --- | --- |
| Install and configure | Follow [platform prerequisites](BEGINNER_SETUP.md#choose-the-instructions-for-your-computer) and [private local configuration](BEGINNER_SETUP.md#initialize-the-private-local-configuration) in the host terminal. | The initializer saves the reviewed configuration without displaying secrets. Continue to the explicit build/preparation flow. |
| Prepare assets | Follow [Build, prepare, check, and start](INSTALL.md#build-prepare-check-and-start). The host launcher runs preparation in the worker environment and persistent software/database volumes. | Required assets have recorded identities; preparation finishes or names the failed asset. A saved configuration or responsive web page alone is insufficient. |
| Check readiness | Use the documented `check-runtime` worker command and Runtime status view. Fresh prepared-only configurations check assets on startup; older configurations retain their configured startup policy. | The check reports readiness for the requested scope without acquisition. Resolve missing required assets before submitting the first job. |
| Run and inspect | Follow [the first small accession job](BEGINNER_SETUP.md#submit-one-small-accession-run) in the browser. Save result access privately. | Inspect terminal state, applicable outputs, exclusions and package manifest. Zero calls can be valid; this installation check is not a biological benchmark. |
| Diagnose failures | Follow [installation troubleshooting](INSTALL.md#troubleshooting) from the host terminal and inspect the job's private logs locally. | Distinguish preparation, admission, input, scientific and rendering failures. Correct the named cause; preserve failed-attempt evidence and do not treat retained outputs as a new success. |
| Update and recover | Follow [safe updates](BEGINNER_SETUP.md#update-safely), [backups](INSTALL.md#back-up-the-job-data-volume) and [return after shutdown](BEGINNER_SETUP.md#return-after-machine-shutdown). | Preserve configuration, credentials, source/image identities and volumes. Check readiness and saved results after the change; use a separately validated restore/rollback plan if recovery is needed. |

The socket-free external profile has different provisioning requirements; use
[the Slurm/external executor guide](CADES_SLURM_BACKEND.md). Local Docker
instructions do not establish external-executor, WSL2 or macOS validation.
A contributor should record which environments were actually exercised.

## Validate the change you made

| Validation question | Required evidence |
| --- | --- |
| Format and provenance integrity | Exact input/output inventories, sequence/record/CDS maps, checksums, coordinates, partial/isoform semantics and actual producer/runtime/assets. Test missing, corrupt and duplicate data. Integrity does not establish biological correctness. |
| Software integration | Focused tests of settings, routing, adapters, readers, manifests, truthful empty/failure/inapplicable/current/cache/retained states, resource limits and whole-process cancellation. Test real supported adapters in addition to mocks before claiming runtime support. |
| Scientific suitability | For changed predictions or methods, define intended taxa/use, independent truth and evaluation criteria before scoring. Separate training from held-out evaluation, audit evidence/homolog leakage, report per-case errors and denominators, and examine consequential downstream differences. Successful exits or higher gene/BGC/BUSCO counts alone do not establish improvement. |
| Rendering | Verify preserved input counts/identities, legends, labels, layout, sparse/empty/large cases, optional formats and actual browser/export appearance. Separate display changes from scientific filtering or classification. |
| Packaging and compatibility | Verify source-to-image COPY closure, imports in installed layouts, old-result readers, exact exported files/checksums, relative assets and portable joins after extraction. A source-tree test cannot prove image inclusion. |
| Production readiness | Independently verify the selected deployment's isolation, resources, prepared assets, access control, observed behavior, upgrade and recovery. Local tests and documentation checks do not establish deployment readiness. |

The repository [CI workflow](../.github/workflows/ci.yml) defines syntax,
Compose, public-source safety/link checks and the unit suite. From the repository
root, the existing documentation check is:

```bash
GIT_OPTIONAL_LOCKS=0 git -c diff.autoRefreshIndex=false diff --check
GIT_OPTIONAL_LOCKS=0 GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=diff.autoRefreshIndex GIT_CONFIG_VALUE_0=false python3 -B bin/check_public_release.py
```

Success means no whitespace errors in the tracked diff and a passing public
safety/local-file-link report. Also inspect new files, which `git diff --check`
does not include, and verify Markdown heading anchors and source identifiers.
For implementation changes, select the corresponding focused tests and then
applicable combined checks. Report skipped cases, failed attempts and commands
that were inspected but not executed. Do not claim fresh installation, scientific
accuracy or platform coverage from static inspection.

## Package, migrate and recover

`Dockerfile.worker` copies root shell scripts, `bin/`, configuration and selected
support modules/recipes into the worker's installed layout. Some shared Python
modules also exist under `/app`; the annotation helpers import policy under
`/clusterweave/web`. `Dockerfile.web` copies its API/result readers and browser
assets separately. Inspect [both](../Dockerfile.worker)
[Dockerfiles](../Dockerfile.web), the [Docker context exclusions](../.dockerignore)
and transitive imports whenever an owner moves or a dependency is added. Verify
actual copied bytes and execution outside the source checkout. Include sourced
modules with copied shell entrypoints and dependencies with generated panel
commands.

Cache compatibility has several boundaries. [cached_genbank.py](../bin/cached_genbank.py)
identifies preparation; [cached_accession.py](../bin/cached_accession.py)
identifies retrieval and annotation/detection; [accession_cache.py](../bin/accession_cache.py)
validates storage/publication. Preparation and detection include explicit source
closures, so an apparently internal module change can invalidate both. The
[cache reference](ACCESSION_CACHE.md#identity-and-validation) explains exact
runtime, database, model and input identities. BiG-SCAPE and downstream work
remain job-specific. Unknown identities must not be replaced with current
versions or inferred from an accession name.

For a tool or interface migration:

1. Inventory old CLI/environment values, web settings, saved job routes,
   producer names, output formats and portable consumers. Name the intended
   compatibility interval and removal criteria only when adoption is decided.
2. Give changed scientific methods distinct producer/profile identities and
   explicit configuration. Preserve old values' meaning during supported
   compatibility; reject unsupported conflicts with actionable instructions.
   Retain historical result readers and original signed packages.
3. Update runtime preparation, capabilities, citations and observed-version
   reporting together. Review [third-party software and data](../THIRD_PARTY.md)
   for the exact assets/use being introduced; source licensing does not cover
   every downloaded component, model or database.
4. Verify cold/warm preparation, cache misses/hits/invalidation where supported,
   source/image closure, CLI/web behavior and package extraction. Do not migrate
   or relabel historical cache producers merely to improve hit rates.
5. Retain the prior source package, images, runtime/model/database identities and
   protected local configuration. Test rollback in an isolated instance before
   relying on it. Restore selection for future jobs while preserving already
   produced results under their original identities; do not overwrite old
   evidence with a rebuild under the same label.

A documentation change creates a new source package identity. `README.md` and
`docs/` are outside the current Docker COPY inputs. The worker copies
`THIRD_PARTY.md`, and both images include `CITATION.cff`. Markdown inside copied
tool-recipe directories and code/help text inside copied source can also affect
image contents. Inspect the scientific cache source closures separately and
record the affected image, cache and result-consumer dependencies.
