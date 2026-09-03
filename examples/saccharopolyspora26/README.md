# Saccharopolyspora 26-assembly example

This bacterial example preserves the exact 26 versioned RefSeq accessions in the public BGCFlow v0.9.0 `mq_saccharopolyspora` example. All assemblies followed the Prodigal-plus-antiSMASH route. FunBGCeX is explicitly `taxonomically_inapplicable`; its non-execution is neither `completed_no_detection` nor biological absence.

ClusterWeave organized 816 antiSMASH candidates. All 816 applicable candidate keys reconciled to staged BiG-SCAPE records and selected-view assignments across all 26 assemblies, with zero applicable unassigned candidates. The 411 distinct selected families are reported only as an aggregate; run-local identifiers are omitted and family correctness is not asserted.

The taxon/GCF figure uses two distinct summaries. The per-genome shared percentage is the number of unique GCFs assigned to that genome that are also found in at least one other submitted genome, divided by all unique GCFs assigned to that genome. A pairwise matrix value is the shared GCF count divided by the nonredundant union of GCFs in the two genomes. The matrix displays at most the 80 genome pairs with the largest shared-GCF counts; a blank cell can represent an undisplayed lower-ranked pair and must not be interpreted as zero overlap.

Use `accession_manifest.tsv` for retrieval, `COMMANDS.md` for portable templates, [`figures/`](figures/) for the representative panel figures, and the root data dictionary for every table. The synteny-resolved geosmin evidence record is under [`focal_locus_geosmin/`](focal_locus_geosmin/).

Panel source: BGCFlow v0.9.0 public `mq_saccharopolyspora` report, <https://nbchub.github.io/bgcflow_report_demo/>.
