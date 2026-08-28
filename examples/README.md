# ClusterWeave public examples

These compact examples describe two completed ClusterWeave 1.0.2 applications without redistributing genomes or private execution records.

| Example | Taxon | Versioned assemblies | Candidate rows | Scope |
| --- | --- | ---: | ---: | --- |
| [`flavi19/`](flavi19/) | Fungi | 19 | 2,120 | The accession-defined newly sequenced section *Flavi* panel from Kjærbølling et al. (2020) |
| [`saccharopolyspora26/`](saccharopolyspora26/) | Bacteria | 26 | 816 | The exact accession panel in the public BGCFlow v0.9.0 `mq_saccharopolyspora` example |

Use each `accession_manifest.tsv` with NCBI Datasets rather than treating genome sequences as redistributed example assets. `summary.tsv` provides supported panel aggregates, and `state_definitions.tsv` preserves all six analysis states. Column definitions and interpretation limits are in [`DATA_DICTIONARY.md`](DATA_DICTIONARY.md).

Component predictions, similarity scores, product labels, and family assignments are evidence organized by ClusterWeave, not biological ground truth. `completed_no_detection` means that an applicable component completed without reporting the feature; it must not be rewritten as biological absence. `taxonomically_inapplicable`, `failed_or_incomplete`, `not_generated_or_unavailable`, and `unresolved` are also distinct states.

Sources:

- Kjærbølling et al. (2020), *Nature Communications*, [doi:10.1038/s41467-019-14051-y](https://doi.org/10.1038/s41467-019-14051-y).
- BGCFlow v0.9.0 public `mq_saccharopolyspora` report: <https://nbchub.github.io/bgcflow_report_demo/>.
- Assembly records and sequence retrieval: [NCBI Datasets](https://www.ncbi.nlm.nih.gov/datasets/genome/).
