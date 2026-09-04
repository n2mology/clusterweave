# Section Flavi 19-assembly example

This fungal example uses the 19 newly sequenced assemblies from Kjærbølling et al. (2020), not the broader 23-species comparison. All 19 assemblies followed the fungal annotation, antiSMASH, FunBGCeX, and selected-view GCF routes. The 2,120 candidate rows comprise 1,584 shared coordinate-overlap pairs, 145 antiSMASH-only rows, and 391 FunBGCeX-only rows.

Five source-study names differ from current NCBI nomenclature; `accession_manifest.tsv` preserves both names without substituting assemblies. The matching rule accepts every positive overlap on a normalized scaffold, sorts by decreasing overlap length, and greedily selects one-to-one pairs. These pairs and component product labels are review evidence, not biological truth.

The taxon/GCF figure uses two distinct summaries. The per-genome shared percentage is the number of unique GCFs assigned to that genome that are also found in at least one other submitted genome, divided by all unique GCFs assigned to that genome. A pairwise matrix value is the shared GCF count divided by the nonredundant union of GCFs in the two genomes. The current visibility default is `auto`, which displays every genome pair with a positive shared-GCF count. This regenerated example therefore includes all 171 positive genome-pair edges; a blank lower-triangular cell means zero shared GCFs. An operator can set `PHYLOGENY_MAX_VISIBLE_ARCS` to a nonnegative numeric limit to retain the ranked bounded display; with a numeric limit, a blank cell can represent an undisplayed lower-ranked pair and must not be interpreted as zero overlap.

Use `accession_manifest.tsv` for retrieval, `COMMANDS.md` for portable templates, [`figures/`](figures/) for the representative panel figures, and the root data dictionary for every table. The synteny-resolved aspirochlorine evidence record is under [`focal_locus_aspirochlorine/`](focal_locus_aspirochlorine/).

Source: Kjærbølling et al. (2020), *Nature Communications*, [doi:10.1038/s41467-019-14051-y](https://doi.org/10.1038/s41467-019-14051-y).
