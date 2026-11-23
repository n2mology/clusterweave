# Architecture

ClusterWeave prepares pinned tool environments, routes genome inputs, schedules
analysis within available resources, and assembles results for review. It keeps
tool reports and scientific exports alongside linked summaries and figures.
The application combines a web/API service, persistent job storage, a worker,
shell stages and Python renderers.

[Extending ClusterWeave](EXTENDING.md) traces the source modules, runtime assets,
readers, caches and packages involved in contributor changes. For installation,
start with [Beginner setup](BEGINNER_SETUP.md).

```text
browser -> web/API -> job store -> worker/admission
                                -> prepare and taxon route
                                   |-- fungi: existing CDS or funannotate
                                   |           -> antiSMASH -> FunBGCeX
                                   |-- bacteria: feature-free GenBank
                                   |           -> antiSMASH + Prodigal
                                   |-- plants: supplied translated CDS
                                               -> plantiSMASH
                                -> shared BiG-SCAPE
                                -> summaries / clinker / figures
                                -> optional bounded phylogeny/evidence
```

The web pipeline prepares inputs, runs the four-stage `run_clusterweave.sh`
wrapper, then invokes figures and selected follow-ups before packaging. Direct
CLI preparation and follow-ups use separate entrypoints.

NCBI taxonomy is authoritative. Each job freezes `analysis_scope` and a
canonical per-genome route. Inputs exist under explicit
`data/genomes/fungi/<project>`, `data/genomes/bacteria/<project>` and
`data/genomes/plants/<project>` roots. Downstream tools use the same per-genome
route manifest.

The core taxonomy/BGC/GCF renderer is dependency-light and writes a static SVG,
Newick, leaf/edge tables, GraphML, methods/manifest JSON, and an exact tree data
bundle. Fungal and bacterial multipanels share a class/color grammar. GCF arcs
show computational context; they are not transfer claims.

`docker-compose.yml` is the trusted single-user local profile. Its worker
contains a pinned Docker CLI and mounts the host socket to run sibling tool
containers. `clusterweave.yml` is socket-free and requires an external
executor. Public services must supply their own isolation and operations layer.

Important boundaries:

- public job projections and packages are allowlisted and token-gated;
- an authenticated workbench package contains the staged genome GenBank files,
  antiSMASH region GenBank files, canonical FunBGCeX BGC GenBank files, native
  plantiSMASH cluster GenBank files, and a
  portable checksum manifest needed for further scientific review;
- original upload objects and download caches, duplicate tool trees, tool
  databases, logs, scratch files, commands, and route internals stay private;
- resource planning and aggregate worker admission are one bounded system;
- optional sequence inference or cross-kingdom evidence can retain successful
  core outputs when they fail; required sequence inference can fail the job.
  Selected NPLinker execution uses a required-stage call and can also fail it.
