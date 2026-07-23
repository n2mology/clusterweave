# ClusterWeave public examples

Two equally supported, public-safe examples show the v1.0.0 output contract.

| Bundle | Scope | Assemblies | Purpose |
| --- | --- | ---: | --- |
| [`fungi_only/`](fungi_only/) | Fungi | 50 | Retained broad fungal benchmark and fungal-only detector outputs |
| [`mixed/`](mixed/) | Both | 40 | 20 bacterial RefSeq plus 20 fungal assemblies and taxon-aware BGC/GCF outputs |

`fungi_only` preserves the established 50-genome accession set and its curated
derived figures and summaries. `mixed` used project name `example`, no target
genome, no ecology mode, and the v1.0.0 defaults. Its 40 accessions were
verified against NCBI on 2026-07-16, and the canonical Both run completed on
2026-07-22 without substitutions. The bundle includes both generated taxon
maps, four canonical SVGs, and compact derived summaries.

The accession lists are locked v1.0.0 inputs. Do not edit their lists or derived
example outputs in place; a correction belongs to a later version with the
changed accession and reason recorded.

The bundles publish accession lists, safe mappings, derived summary tables, and
selected SVGs only. They exclude job IDs, result tokens, private URLs, raw
genomes, raw tool trees, databases, logs, caches, and absolute paths. A zero-BGC
assembly remains valid example data. An accession is substituted only when that
specific assembly cannot be downloaded or processed; any substitution must use
a current annotated RefSeq assembly from the same species or nearest represented
lineage and be recorded in the bundle README.
