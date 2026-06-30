# ClusterWeave funannotate Runtime Bake

This directory contains the one-time build/prep path for the funannotate v1.8.17 runtime used by ClusterWeave. It bakes old funannotate-compatible BUSCO DB directories into the image/SIF before jobs run. Public jobs must not download BUSCO DBs.

Default DB set:

```text
ascomycota basidiomycota microsporidia dikarya fungi
```

The build script first looks for local cache tarballs in `busco_cache/` using either `<db>.tar.gz` or `<db>_odb9.tar.gz` names. These tarballs are local artifacts and are intentionally ignored by git. If a cache tarball is absent, the build uses `install_busco_db.py` inside the image to read funannotate's legacy ODB9 URL map, follow modern OSF redirects, extract the tarball, rename the root to the old funannotate DB name, and validate `hmms/` during the one-time bake.

Examples:

```bash
# Docker runtime used by lab-docker workers
software/funannotate/build_funannotate_sif.sh docker

# Singularity/Apptainer runtime when a builder exists
software/funannotate/build_funannotate_sif.sh sif

# Inventory and compatibility checks
software/funannotate/build_funannotate_sif.sh inventory
software/funannotate/build_funannotate_sif.sh validate
```

`run_annotation_and_detection.sh` validates the installed DB before `funannotate predict`. It does not run `funannotate setup` or pull missing BUSCO DBs during a job.
