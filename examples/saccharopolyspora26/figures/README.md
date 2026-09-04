# Saccharopolyspora representative figures

- `saccharopolyspora26.taxon_tree.svg` provides ranked taxonomy, per-genome BGC/GCF summaries, and a pairwise GCF-sharing matrix.
- `saccharopolyspora26.bigscape_multipanel.svg` organizes the configured selected-view assignments for all 816 staged antiSMASH candidates across the 26 assemblies.

In the taxon/GCF profile, a genome's shared percentage is its unique GCFs also observed in at least one other submitted genome divided by all unique GCFs assigned to that genome. Pairwise Jaccard is the shared GCF count divided by the nonredundant union for the two genomes. The current visibility default is `auto`, which displays every genome pair with a positive shared-GCF count. This regenerated matrix includes all 280 positive genome-pair edges; a blank lower-triangular cell means zero shared GCFs. A nonnegative numeric limit retains the ranked bounded display; with a numeric limit, a blank cell can represent an undisplayed lower-ranked pair and must not be interpreted as zero overlap.

FunBGCeX is `taxonomically_inapplicable` for this bacterial panel. These figures organize component evidence and complete configured assignment coverage; they do not establish biological family correctness, product identity, or comparative accuracy.
