# Section Flavi 19-assembly example

This fungal example uses the 19 newly sequenced assemblies from Kjærbølling et al. (2020), not the broader 23-species comparison. All 19 assemblies followed the fungal annotation, antiSMASH, FunBGCeX, and selected-view GCF routes. The 2,120 candidate rows comprise 1,584 shared coordinate-overlap pairs, 145 antiSMASH-only rows, and 391 FunBGCeX-only rows.

Five source-study names differ from current NCBI nomenclature; `accession_manifest.tsv` preserves both names without substituting assemblies. The matching rule accepts every positive overlap on a normalized scaffold, sorts by decreasing overlap length, and greedily selects one-to-one pairs. These pairs and component product labels are review evidence, not biological truth.

Use `accession_manifest.tsv` for retrieval, `COMMANDS.md` for portable templates, and the root data dictionary for every table. The approved aspirochlorine evidence record is under `focal_locus_aspirochlorine/`.

Source: Kjærbølling et al. (2020), *Nature Communications*, [doi:10.1038/s41467-019-14051-y](https://doi.org/10.1038/s41467-019-14051-y).
