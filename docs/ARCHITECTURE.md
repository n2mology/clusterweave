# Architecture

ClusterWeave has a small web/API service, a durable job store, one bounded
worker/admission layer, canonical shell stages, and focused Python renderers.

```text
browser -> web/API -> job store -> worker/admission
                                -> prepare and taxon route
                                   |-- fungi: existing CDS or funannotate
                                   |           -> antiSMASH -> FunBGCeX
                                   |-- bacteria: feature-free GenBank
                                               -> antiSMASH + Prodigal
                                -> shared BiG-SCAPE
                                -> summaries / clinker / figures
                                -> optional bounded phylogeny/evidence
```

NCBI taxonomy is authoritative. Each job freezes `analysis_scope` and a
canonical per-genome route. Human-readable inputs remain under explicit
`data/genomes/fungi/<project>` and `data/genomes/bacteria/<project>` roots,
while downstream tools consume one manifest and one unique region universe.

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
- raw genomes, raw tool databases, logs, scratch, and route internals stay
  private;
- resource planning and aggregate worker admission are one bounded system;
- optional sequence inference or cross-kingdom evidence cannot invalidate the
  successful core workflow unless explicitly required.
