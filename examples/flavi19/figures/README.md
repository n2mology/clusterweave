# Section Flavi representative figures

- `flavi19.taxon_tree.svg` provides ranked taxonomy, per-genome BGC/GCF summaries, and a pairwise GCF-sharing matrix.
- `flavi19.bgc_overlap.svg` summarizes 2,120 candidate rows: 1,584 shared coordinate-overlap pairs, 145 antiSMASH-only rows, and 391 FunBGCeX-only rows.
- `flavi19.bigscape_multipanel.svg` organizes selected family, known-cluster, protein, and synteny evidence across the 19 assemblies.
- `focal_locus_aspirochlorine_bigscape_family.svg` is an open-frame view of the aspirochlorine-labelled family. Its node and edge TSVs provide editable coordinates and graph metrics.

In the taxon/GCF profile, a genome's shared percentage is its unique GCFs also observed in at least one other submitted genome divided by all unique GCFs assigned to that genome. Pairwise Jaccard is the shared GCF count divided by the nonredundant union for the two genomes. The current visibility default is `auto`, which displays every genome pair with a positive shared-GCF count. This regenerated matrix includes all 171 positive genome-pair edges; a blank lower-triangular cell means zero shared GCFs. A nonnegative numeric limit retains the ranked bounded display; with a numeric limit, a blank cell can represent an undisplayed lower-ranked pair and must not be interpreted as zero overlap.

The focused network contains all 34 node-table records and all 86 edge-table records. Edge similarity is `1 − BiG-SCAPE distance`, and rendered width is `0.8 + 2 × similarity`. Geometric edge length is determined by the boundary-free layout and does not encode distance. In its title, `aspirochlorine +6` denotes the most frequent displayed component product label plus six additional labels; `83% / 75% / 81%+` lists up to three retained antiSMASH ClusterCompare scores for that primary label, with `+` indicating additional values.

These figures organize component evidence. They do not establish biological family correctness, candidate truth, product identity, or metabolite production.
