# Portable commands: Saccharopolyspora panel

Create an accession list and retrieve public records with NCBI Datasets:

```bash
awk -F '\t' 'NR > 1 { print $1 }' accession_manifest.tsv > accessions.txt
datasets download genome accession \
  --inputfile accessions.txt \
  --include genome,gbff \
  --filename saccharopolyspora26.zip
unzip saccharopolyspora26.zip -d saccharopolyspora26_ncbi
```

For ClusterWeave 1.0.2, submit `accessions.txt` with analysis scope `bacteria`, no target genome, no scientific overrides, 12 CPUs, two workers, three concurrent genomes, and all standard stages except NPLinker.

The public antiSMASH 8.0.4 prediction template was:

```bash
antismash <input.gbk> \
  --minlength 1000 \
  --output-dir <output-directory> \
  --output-basename <record-id> \
  --cpus 1 \
  --taxon bacteria \
  --genefinding-tool prodigal \
  --verbose --fullhmmer --asf --clusterhmmer --tigrfam \
  --cc-mibig --cb-general --cb-knownclusters --cb-subclusters \
  --pfam2go --smcog-trees --tfbs --rre --allow-long-headers
```

This invoked Prodigal V2.6.3 through antiSMASH; there was no separate Prodigal preprocessing command. Record-sharded calls used `--cpus 1`. The single-record/fallback form omitted `--output-basename` and used `--cpus 4`; scientific options were unchanged. FunBGCeX was not invoked because it was taxonomically inapplicable.

The BiG-SCAPE 2.0.0-beta.6 template was:

```bash
bigscape.py cluster \
  -i <staged-antiSMASH-region-directory> \
  -o <output-directory> \
  --input-mode recursive \
  --include-gbk '*' \
  --pfam-path <Pfam-A.hmm> \
  --cores 12 \
  --include-singletons \
  --mix \
  --mibig-version 4.0
```

ClusterWeave selected the `mix` view at clustering threshold 0.3. The portable clinker 0.0.32 alignment form is:

```bash
clinker <ordered-region-1.gbk> <ordered-region-2.gbk> ... \
  -p <panel.html> -o <alignments.tsv> -f -ufo
```

Complete upstream database freeze dates were not available; these templates reproduce recorded public options, not every byte of the original environment.
